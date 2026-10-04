"""Small, testable scheduling policy. All dates and times are US Central."""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_calendar import is_trading_day

CENTRAL = ZoneInfo("America/Chicago")


def plan(now, last_sent="", event="schedule", request_mail=False):
    if now.tzinfo is None:
        raise ValueError("An aware datetime is required")
    now = now.astimezone(CENTRAL)
    today = now.date().isoformat()
    trading = is_trading_day(now.date())
    # A late runner must not silently discard an unsent day's briefing.
    due = trading and now.hour >= 9 and last_sent.strip() != today
    mail = due and (event == "schedule" or request_mail)
    refresh = event == "workflow_dispatch" or mail or 9 <= now.hour < 17
    reason = ("mail_due" if mail else "non_trading_day" if not trading
              else "already_sent" if last_sent.strip() == today
              else "before_0900" if now.hour < 9 else "refresh_only")
    return {"run": refresh, "mail": mail, "today_ct": today, "reason": reason}


def main():
    marker = Path(".mail_sent")
    result = plan(datetime.now(CENTRAL),
                  marker.read_text().strip() if marker.exists() else "",
                  os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch"),
                  os.environ.get("REQUEST_MAIL", "false").lower() == "true")
    lines = [f"{key}={str(value).lower() if isinstance(value, bool) else value}"
             for key, value in result.items()]
    print("gate: " + " ".join(lines))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
