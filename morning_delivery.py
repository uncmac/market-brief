"""Independent morning worker: prepare early, send after 09:00, persist retries."""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from delivery_policy import CENTRAL
from trading_calendar import is_trading_day
from send_mail import configuration, recipient_id, send_once


def eligible(now, last_sent):
    now = now.astimezone(CENTRAL)
    return (is_trading_day(now.date()) and
            (now.hour * 60 + now.minute) >= 8 * 60 + 40 and
            last_sent.strip() != now.date().isoformat())


def marker():
    path = Path('.mail_sent')
    return path.read_text().strip() if path.exists() else ''


def persist():
    """Stop on persistence failure: never blindly resend an accepted message."""
    for name in ('.mail_sent', '.mail_delivery.json'):
        if Path(name).exists():
            subprocess.run(['git', 'add', name], check=True)
    result = subprocess.run(['git', 'diff', '--cached', '--quiet'])
    if result.returncode == 0:
        return
    if result.returncode != 1:
        raise RuntimeError('Cannot inspect delivery state')
    subprocess.run(['git', 'commit', '-m', 'Record morning mail delivery progress'], check=True)
    for attempt in range(3):
        pull = subprocess.run(['git', 'pull', '--rebase', 'origin', 'main'])
        if pull.returncode:
            raise RuntimeError('Delivery state conflict: inspect before resending')
        if subprocess.run(['git', 'push', 'origin', 'HEAD:main']).returncode == 0:
            return
        time.sleep(5)
    raise RuntimeError('Delivery state push failed: inspect before resending')


def verified(env, today):
    _, password, recipients = configuration(env)
    if not Path('.mail_delivery.json').exists():
        return False
    state = json.loads(Path('.mail_delivery.json').read_text())
    return (marker() == today and state.get('date') == today and
            all(recipient_id(r, password) in state.get('accepted', []) for r in recipients))


def run(clock=lambda: datetime.now(CENTRAL), sleep=time.sleep,
        build=None, send=None, save=None, verify=None, attempts=10):
    if not eligible(clock(), marker()):
        print('No unsent trading-day briefing due; exiting without SMTP')
        return
    configuration(os.environ)
    today = clock().date().isoformat()
    build = build or (lambda: subprocess.run(
        [sys.executable, 'market_dashboard.py', '--no-publish', '-o', 'mail_dashboard.html'],
        check=True, timeout=240))
    send = send or (lambda: send_once(os.environ, html_path='mail_dashboard.html'))
    save = save or persist
    verify = verify or (lambda: verified(os.environ, today))
    # Prepare near 09:00 instead of depending on the 09:00 cron arriving on time.
    while clock().hour < 9 and clock().hour * 60 + clock().minute < 539:
        sleep(min(30, (clock().replace(hour=8, minute=59, second=0, microsecond=0)
                       - clock()).total_seconds()))
    for attempt in range(attempts):
        if clock().date().isoformat() != today:
            raise RuntimeError('Central date changed; never send yesterday as today')
        try:
            build()
        except (subprocess.SubprocessError, OSError) as error:
            print(f'Dashboard attempt {attempt + 1} failed: {type(error).__name__}', flush=True)
        else:
            while clock().hour < 9:
                sleep(min(10, (clock().replace(hour=9, minute=0, second=0, microsecond=0)
                               - clock()).total_seconds()))
            try:
                send()
            except (RuntimeError, ValueError, OSError) as error:
                print(f'Mail attempt {attempt + 1} failed: {type(error).__name__}', flush=True)
            # Outside the send exception handler: failed state persistence MUST abort.
            save()
            if verify():
                print('VERIFIED: SMTP accepted all recipients; durable daily record saved', flush=True)
                return
        if attempt + 1 < attempts:
            sleep(60)
    raise RuntimeError('Retries exhausted in this run; next scheduled check will retry')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        due = eligible(datetime.now(CENTRAL), marker())
        print(f'morning mail needed: {due}')
        with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
            out.write(f'due={str(due).lower()}\n')
    else:
        run()


if __name__ == '__main__':
    main()
