#!/usr/bin/env python3
"""Send one trading-day briefing; persist accepted recipients for safe retries.

SMTP acceptance is not inbox delivery. A connection loss after DATA can leave
delivery ambiguous; SMTP cannot offer an exactly-once guarantee.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import smtplib
import ssl
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import format_datetime, getaddresses
from html import unescape
from pathlib import Path

from delivery_policy import CENTRAL, plan

URL = "https://uncmac.github.io/market-brief/"


class DeliveryPersistenceError(RuntimeError):
    """Acceptance could not be saved; automatic SMTP retries must stop."""


def configuration(env):
    values = [env.get(key, "").strip() for key in ("MAIL_FROM", "MAIL_PASS", "MAIL_TO")]
    if not all(values):
        raise ValueError("Required mail settings missing: MAIL_FROM, MAIL_PASS, MAIL_TO")
    sender, password, raw_to = values
    if any(char in sender + raw_to for char in "\r\n"):
        raise ValueError("Mail addresses must not contain line breaks")
    recipients = list(dict.fromkeys(address for _, address in
                                   getaddresses([raw_to.replace(";", ",")])))
    if not recipients or any(not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", x)
                             for x in [sender, *recipients]):
        raise ValueError("MAIL_FROM or MAIL_TO contains an invalid email address")
    return sender, password, recipients


def make_message(html, sender, recipients, now):
    def find(pattern):
        match = re.search(pattern, html)
        return unescape(match.group(1).strip()) if match else ""

    verdict = find(r'class="verdict"[^>]*>([^<]+)<')
    score = find(r'class="score mono"[^>]*>([^<]+)<')
    action = find(r'권장 행동: ([^<]+)<')
    asof = find(r'기준일 <b>([^<]+)</b>')
    kind = find(r'기준일 <b>[^<]+</b> ([^<]+)<')
    warn = find(r'class="tag warn">([^<]+)<')
    if not all((verdict, score, action, asof)):
        raise ValueError("Dashboard summary is incomplete; refusing an empty briefing")
    now = now.astimezone(CENTRAL)
    warn_line = f"\n참고: {warn}" if warn else ""
    body = f"""오늘의 시장 브리핑이 갱신되었습니다.

기준일: {asof} {kind}{warn_line}
종합 판정: {verdict} ({score} / ±100)
권장 행동: {action}

전체 대시보드 보기:
{URL}

(미국 증시 거래일 중부시간 오전 9시 발송을 목표로 합니다.
예약 실행이나 데이터 수집이 지연되면 늦게 도착할 수 있습니다.)"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"📈 오늘의 시장 브리핑 · {now:%Y-%m-%d} · {verdict}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Date"] = format_datetime(now)
    # Same ID on retries helps diagnostics; mail servers need not deduplicate it.
    msg["Message-ID"] = f"<market-brief.{now:%Y-%m-%d}@{sender.split('@')[1]}>"
    return msg


def atomic_write(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def recipient_id(address, password):
    # This ledger is committed to a public repository. Never store addresses or
    # unsalted email hashes, which are easy to enumerate.
    return hmac.new(password.encode(), address.encode(), hashlib.sha256).hexdigest()


def deliver(sender, password, recipients, message, accepted, checkpoint,
            smtp_factory=smtplib.SMTP_SSL, sleep=time.sleep):
    pending = [r for r in recipients if recipient_id(r, password) not in accepted]
    for attempt in range(1, 4):
        if not pending:
            return
        try:
            with smtp_factory("smtp.gmail.com", 465,
                              context=ssl.create_default_context(), timeout=60) as smtp:
                smtp.login(sender, password)
                try:
                    refused = smtp.sendmail(sender, pending, message.as_string())
                except smtplib.SMTPRecipientsRefused as error:
                    refused = error.recipients
                newly_accepted = [r for r in pending if r not in refused]
                accepted.update(recipient_id(r, password) for r in newly_accepted)
                # Persist before QUIT: QUIT failure must not resend accepted mail.
                try:
                    checkpoint(accepted)
                except OSError:
                    # A disk failure is not a transport failure. Stop instead of
                    # retrying mail whose acceptance could not be recorded.
                    raise DeliveryPersistenceError("Cannot persist accepted recipients; inspect before retrying") from None
                pending = [r for r in pending if r in refused]
            print(f"SMTP attempt {attempt}: {len(newly_accepted)} accepted, "
                  f"{len(pending)} pending (addresses withheld)")
        except (smtplib.SMTPException, OSError) as error:
            # Do not print raw SMTP errors: they can include recipient addresses.
            print(f"SMTP attempt {attempt}: {type(error).__name__}")
        if pending and attempt < 3:
            sleep(30 * attempt)
    if pending:
        raise RuntimeError(f"SMTP did not accept {len(pending)} recipient(s); retry required")


def send_once(env, now=None, html_path="index.html", marker_path=".mail_sent",
              state_path=".mail_delivery.json", smtp_factory=smtplib.SMTP_SSL,
              sleep=time.sleep):
    sender, password, recipients = configuration(env)
    now = now or datetime.now(CENTRAL)
    marker = Path(marker_path)
    decision = plan(now, marker.read_text().strip() if marker.exists() else "")
    if not decision["mail"]:
        print(f"Mail skipped: {decision['reason']}")
        return False
    today = decision["today_ct"]
    state_file = Path(state_path)
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    accepted = set(state.get("accepted", [])) if state.get("date") == today else set()

    def checkpoint(ids):
        atomic_write(state_file, json.dumps({"date": today, "accepted": sorted(ids)},
                                           indent=2) + "\n")

    message = make_message(Path(html_path).read_text(encoding="utf-8"),
                           sender, recipients, now)
    deliver(sender, password, recipients, message, accepted, checkpoint,
            smtp_factory=smtp_factory, sleep=sleep)
    atomic_write(marker, today + "\n")
    print(f"SMTP accepted briefing for all {len(recipients)} recipient(s)")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    if args.check_config:
        configuration(os.environ)
        print("Mail configuration is present and addresses are valid (SMTP not contacted)")
    else:
        send_once(os.environ)


if __name__ == "__main__":
    main()
