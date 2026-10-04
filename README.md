# Market brief

Daily market dashboard: https://uncmac.github.io/market-brief/

## Delivery schedule

- Target: **09:00 America/Chicago on US stock market trading days**. The timezone
  handles daylight saving time. Weekends and full-day exchange holidays never send.
- GitHub Actions schedules are best effort, not a punctual delivery guarantee.
  The 09:17/09:47 and subsequent daytime runs recover an unsent briefing if the
  09:00 run is delayed or dropped. A run arriving after 13:00 can still send that
  Central day's briefing. No prior-day backfill is sent.
- Each run finishes after one dashboard refresh; it no longer sleeps for hours.
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

**Safe manual refresh:** Actions → dashboard-updates → Run workflow, leaving
`send_mail` unchecked (the default). This updates the dashboard without sending.
Checking `send_mail` requests any unsent briefing for today, still restricted to
trading days after 09:00 Central and subject to the delivery ledger.

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
