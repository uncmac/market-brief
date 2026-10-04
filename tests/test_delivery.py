import json
import smtplib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from delivery_policy import CENTRAL, plan
from send_mail import configuration, make_message, recipient_id, send_once

ENV = {"MAIL_FROM": "sender@example.com", "MAIL_PASS": "fake-test-password",
       "MAIL_TO": "first@example.com,second@example.com"}
HTML = ('<div class="verdict">관망</div><div class="score mono">+12</div>'
        '<p>권장 행동: 분할 접근</p><p>기준일 <b>2026-10-01</b> 종가</p>')


def central(value):
    return datetime.fromisoformat(value).replace(tzinfo=CENTRAL)


class PolicyTests(unittest.TestCase):
    def test_late_runner_regression(self):
        # Actual missed run on October 2: UTC 18:43 == Central 13:43.
        for hour in ("13:43", "18:00", "23:59"):
            self.assertTrue(plan(central(f"2026-10-02T{hour}"), "2026-09-24")["mail"])

    def test_nine_am_boundary(self):
        self.assertFalse(plan(central("2026-10-02T08:59"))["mail"])
        self.assertTrue(plan(central("2026-10-02T09:00"))["mail"])

    def test_dst_and_utc_dates(self):
        for before, at in [("2026-10-02T13:59+00:00", "2026-10-02T14:00+00:00"),
                           ("2026-12-01T14:59+00:00", "2026-12-01T15:00+00:00")]:
            self.assertFalse(plan(datetime.fromisoformat(before))["mail"])
            self.assertTrue(plan(datetime.fromisoformat(at))["mail"])
        result = plan(datetime.fromisoformat("2026-10-03T01:00+00:00"))
        self.assertEqual(result["today_ct"], "2026-10-02")
        self.assertTrue(result["mail"])

    def test_weekends_and_observed_holidays(self):
        for day in ("2026-10-03", "2026-10-04", "2026-07-03", "2026-11-26",
                    "2027-03-26", "2027-06-18", "2027-12-24"):
            with self.subTest(day=day):
                self.assertFalse(plan(central(day + "T09:00"), event="workflow_dispatch",
                                      request_mail=True)["mail"])

    def test_early_close_is_trading_day(self):
        self.assertTrue(plan(central("2026-11-27T09:00"))["mail"])

    def test_manual_default_does_not_send(self):
        now = central("2026-10-02T09:00")
        self.assertFalse(plan(now, event="workflow_dispatch")["mail"])
        self.assertTrue(plan(now, event="workflow_dispatch", request_mail=True)["mail"])

    def test_marker_prevents_duplicates_even_when_manually_requested(self):
        self.assertFalse(plan(central("2026-10-02T10:00"), "2026-10-02\n",
                              event="workflow_dispatch", request_mail=True)["mail"])

    def test_fail_closed_for_unknown_calendar_and_naive_time(self):
        with self.assertRaises(ValueError):
            plan(central("2028-01-03T09:00"))
        with self.assertRaises(ValueError):
            plan(datetime(2026, 10, 2, 9))


class MailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.html = self.root / "index.html"
        self.html.write_text(HTML, encoding="utf-8")
        self.marker = self.root / ".mail_sent"
        self.state = self.root / ".mail_delivery.json"
        self.calls = []

    def factory(self, results, quit_failure=False):
        results = iter(results)
        def create(*args, **kwargs):
            smtp = Mock()
            def send(sender, recipients, message):
                self.calls.append(list(recipients))
                result = next(results)
                if isinstance(result, Exception):
                    raise result
                return result
            smtp.sendmail.side_effect = send
            context = Mock()
            context.__enter__ = Mock(return_value=smtp)
            context.__exit__ = Mock(return_value=False)
            if quit_failure:
                context.__exit__.side_effect = smtplib.SMTPServerDisconnected("QUIT failed")
            return context
        return Mock(side_effect=create)

    def send(self, factory, **kwargs):
        return send_once(ENV, now=central("2026-10-02T13:43"), html_path=self.html,
                         marker_path=self.marker, state_path=self.state,
                         smtp_factory=factory, sleep=lambda _: None, **kwargs)

    def test_configuration_fails_loudly(self):
        for values in ({}, dict(ENV, MAIL_PASS=""), dict(ENV, MAIL_TO="broken"),
                       dict(ENV, MAIL_TO="x@example.com\nBcc: y@example.com")):
            with self.subTest(values=list(values)):
                with self.assertRaises(ValueError):
                    configuration(values)
        self.assertEqual(configuration(dict(ENV, MAIL_TO="a@example.com; a@example.com"))[2],
                         ["a@example.com"])

    def test_success_and_rerun(self):
        factory = self.factory([{}])
        self.assertTrue(self.send(factory))
        self.assertEqual(self.marker.read_text().strip(), "2026-10-02")
        self.assertFalse(self.send(factory))
        self.assertEqual(factory.call_count, 1)
        state = self.state.read_text()
        self.assertNotIn("@", state)
        self.assertNotIn(ENV["MAIL_PASS"], state)
        self.assertEqual(len(json.loads(state)["accepted"]), 2)

    def test_partial_failure_retries_only_refused_recipient(self):
        self.send(self.factory([{"second@example.com": (450, b"try later")}, {}]))
        self.assertEqual(self.calls, [["first@example.com", "second@example.com"],
                                      ["second@example.com"]])
        self.assertTrue(self.marker.exists())

    def test_persistent_partial_failure_and_next_run_recovery(self):
        refused = {"second@example.com": (550, b"rejected")}
        with self.assertRaises(RuntimeError):
            self.send(self.factory([refused, smtplib.SMTPRecipientsRefused(refused), refused]))
        self.assertFalse(self.marker.exists())
        self.assertEqual(len(json.loads(self.state.read_text())["accepted"]), 1)
        self.send(self.factory([{}]))
        self.assertEqual(self.calls[-1], ["second@example.com"])
        self.assertTrue(self.marker.exists())

    def test_transport_failure_leaves_no_sent_marker(self):
        with self.assertRaises(RuntimeError):
            self.send(self.factory([smtplib.SMTPServerDisconnected("failed")] * 3))
        self.assertFalse(self.marker.exists())

    def test_quit_failure_does_not_resend_accepted_mail(self):
        factory = self.factory([{}], quit_failure=True)
        self.send(factory)
        self.assertEqual(factory.call_count, 1)
        self.assertTrue(self.marker.exists())

    def test_checkpoint_disk_failure_stops_without_retry(self):
        factory = self.factory([{}])
        with patch("send_mail.atomic_write", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "Cannot persist"):
                self.send(factory)
        self.assertEqual(factory.call_count, 1)
        self.assertFalse(self.marker.exists())

    def test_old_ledger_does_not_suppress_today(self):
        ids = [recipient_id(r, ENV["MAIL_PASS"]) for r in configuration(ENV)[2]]
        self.state.write_text(json.dumps({"date": "2026-10-01", "accepted": ids}))
        self.send(self.factory([{}]))
        self.assertEqual(len(self.calls[0]), 2)

    def test_all_accepted_ledger_recovers_missing_marker_without_smtp(self):
        ids = [recipient_id(r, ENV["MAIL_PASS"]) for r in configuration(ENV)[2]]
        self.state.write_text(json.dumps({"date": "2026-10-02", "accepted": ids}))
        factory = self.factory([])
        self.send(factory)
        factory.assert_not_called()
        self.assertTrue(self.marker.exists())

    def test_bad_html_does_not_send(self):
        self.html.write_text("error page")
        factory = self.factory([])
        with self.assertRaises(ValueError):
            self.send(factory)
        factory.assert_not_called()
        self.assertFalse(self.marker.exists())

    def test_subject_uses_central_day_and_decodes_entities(self):
        msg = make_message(HTML.replace("분할 접근", "A &amp; B"), ENV["MAIL_FROM"],
                           configuration(ENV)[2], datetime.fromisoformat("2026-10-03T01:00+00:00"))
        self.assertIn("2026-10-02", msg["Subject"])
        self.assertIn("A & B", msg.get_payload(decode=True).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
