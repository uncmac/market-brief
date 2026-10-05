# Market brief

Daily market dashboard: https://uncmac.github.io/market-brief/

## Delivery schedule

- Target: **09:00 America/Chicago on US stock market trading days**. The timezone
  handles daylight saving time. Weekends and full-day exchange holidays never send.
- `morning-mail` is independent of dashboard publishing. It prepares at 08:41
  and 08:51, builds near 08:59 and waits until 09:00 before attempting SMTP.
- Every five minutes from 09:00 through 23:55 Central, a scheduled check exits
  immediately if today is already sent. Otherwise it retries the missing briefing.
  A worker retries failed builds/mail up to ten cycles, waiting 60 seconds between
  cycles; SMTP also retries at 30/60-second intervals. Partial acceptance is saved
  after each cycle and already accepted recipients are excluded from retries.
- These are requested schedule times, not guaranteed execution times. GitHub may
  delay/drop ALL morning triggers. More triggers improve recovery opportunities,
  but an independent hosted scheduler/executor is needed for stronger punctuality.
- Success requires all configured recipients' SMTP receipts AND the durable daily
  marker. Persistence errors stop that worker instead of blindly resending.
- Dashboard refreshes run separately at 09:00, hourly at :17 from 10:17–16:17,
  and once on weekends. A publishing failure cannot prevent the mail attempt.
- `.mail_sent` is the Central date when SMTP accepted mail for all recipients.
  `.mail_delivery.json` tracks partial acceptance so retries skip those recipients.
  It stores keyed identifiers, never email addresses. Changing the mail password
  during a partial delivery invalidates those identifiers; inspect before retrying.
- SMTP acceptance does not prove inbox placement. A lost connection after SMTP DATA,
  or failure to push the delivery ledger after sending, can leave delivery ambiguous.
  Review failed runs before manually retrying in those cases.
- The shared calendar is explicit for 2026–2027. Update `trading_calendar.py` before
  2028; unknown years fail closed instead of sending on an unverified holiday.

The October 2026 delivery fix addresses runs that started hours late and were
silently excluded by the previous 13:00 cutoff. For example, the October 2 run
started at 13:43 Central and completed successfully without sending. Missing mail
settings and partial recipient refusals now fail visibly instead of being marked
as fully delivered.

## Operations

Repository Actions secrets: `MAIL_FROM`, `GMAIL_APP_PASSWORD`, `MAIL_TO` (comma- or
semicolon-separated addresses). Do not commit credentials or recipient lists.

**Safe manual refresh:** Actions → dashboard-updates → Run workflow updates
only the dashboard. Actions → morning-mail → Run workflow checks and retries the
unsent trading-day briefing (preparation starts no earlier than 08:40; SMTP no
earlier than 09:00). Re-running after success verifies the receipts without SMTP.

Failed settings, build, SMTP, or persistence steps make the workflow fail. Inspect
the delivery summary and failed step in Actions. Provider-specific bounce or spam
diagnostics still need to be checked in the sender's mailbox.

If punctual 09:00 delivery is required, move scheduling and execution to a service
with stronger timing guarantees. Triggering GitHub externally can improve dispatch
reliability, but cannot guarantee prompt GitHub runner availability.

## Local verification (no email)

```sh
python -m pip install numpy pandas requests tzdata
python -m unittest discover -s tests -v
python market_dashboard.py --demo --no-publish -o demo.html
```

Tests use fake SMTP servers and temporary ledgers. `--no-publish` prevents the
dashboard script's optional local GitHub publishing helper from running. Running
`send_mail.py` without `--check-config` is a real send attempt: do not use it as a
test against production credentials.

## October 5 follow-up

The first scheduled dashboard run on October 5 was created at 21:23 UTC
(16:23 Central). Its SMTP log confirms four accepted recipients at 16:24:12.
This was late scheduler delivery, not a rejected Gmail login. The independent
morning workflow adds early preparation, five-minute recovery checks and tested
in-worker retries; it does not claim that GitHub now guarantees 09:00 execution.
The computer does not have to stay on. Inbox/spam placement is not visible here.
