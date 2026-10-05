import os
import subprocess
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from delivery_policy import CENTRAL
from morning_delivery import eligible, run

ENV = {'MAIL_FROM': 'sender@example.com', 'MAIL_PASS': 'test-only',
       'MAIL_TO': 'one@example.com'}


class MorningTests(unittest.TestCase):
    def test_prearm_and_holidays(self):
        for date, expected in [('2026-10-06T08:39', False),
                               ('2026-10-06T08:41', True),
                               ('2026-10-06T23:55', True),
                               ('2026-10-10T09:00', False),
                               ('2026-11-26T09:00', False)]:
            now = datetime.fromisoformat(date).replace(tzinfo=CENTRAL)
            self.assertEqual(eligible(now, ''), expected)
            self.assertFalse(eligible(now, now.date().isoformat()))

    @patch.dict(os.environ, ENV)
    @patch('morning_delivery.marker', return_value='')
    def test_waits_until_nine_both_dst_regimes(self, _):
        for date in ('2026-10-06', '2026-12-01'):
            now = [datetime.fromisoformat(date + 'T08:51').replace(tzinfo=CENTRAL)]
            sends = []
            def sleep(seconds):
                self.assertGreater(seconds, 0)
                now[0] += timedelta(seconds=seconds)
            run(clock=lambda: now[0], sleep=sleep, build=lambda: None,
                send=lambda: sends.append(now[0]), save=lambda: None, verify=lambda: True)
            self.assertEqual(sends[0].strftime('%H:%M:%S'), '09:00:00')

    @patch.dict(os.environ, ENV)
    @patch('morning_delivery.marker', return_value='')
    def test_build_then_send_failures_recover_and_checkpoint(self, _):
        build = Mock(side_effect=[subprocess.TimeoutExpired('build', 240), None, None])
        send = Mock(side_effect=[RuntimeError('SMTP unavailable'), None])
        save = Mock()
        run(clock=lambda: datetime(2026, 10, 6, 9, tzinfo=CENTRAL), sleep=lambda _: None,
            build=build, send=send, save=save, verify=Mock(side_effect=[False, True]))
        self.assertEqual(build.call_count, 3)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(save.call_count, 2)

    @patch.dict(os.environ, ENV)
    @patch('morning_delivery.marker', return_value='')
    def test_persistence_failure_never_triggers_resend(self, _):
        send = Mock()
        with self.assertRaisesRegex(RuntimeError, 'persist failed'):
            run(clock=lambda: datetime(2026, 10, 6, 9, tzinfo=CENTRAL),
                build=lambda: None, send=send,
                save=Mock(side_effect=RuntimeError('persist failed')), verify=lambda: True)
        self.assertEqual(send.call_count, 1)

    @patch('morning_delivery.marker', return_value='2026-10-06')
    def test_already_sent_never_builds_or_sends(self, _):
        build, send = Mock(), Mock()
        run(clock=lambda: datetime(2026, 10, 6, 9, tzinfo=CENTRAL), build=build, send=send)
        build.assert_not_called()
        send.assert_not_called()

    @patch.dict(os.environ, ENV)
    @patch('morning_delivery.marker', return_value='')
    def test_exhaustion_is_failure_not_green_success(self, _):
        with self.assertRaisesRegex(RuntimeError, 'Retries exhausted'):
            run(clock=lambda: datetime(2026, 10, 6, 9, tzinfo=CENTRAL),
                sleep=lambda _: None, build=lambda: None,
                send=Mock(side_effect=RuntimeError('mail failed')), save=lambda: None,
                verify=lambda: False, attempts=2)


if __name__ == '__main__':
    unittest.main()
