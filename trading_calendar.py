"""NYSE full-day closures shared by the dashboard and delivery policy."""

# Observed dates; early closes are still trading days. Extend before 2028.
US_MARKET_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}


def is_trading_day(day):
    if day.year not in (2026, 2027):
        raise ValueError("Update the market holiday calendar for this year before sending mail")
    return day.weekday() < 5 and day.isoformat() not in US_MARKET_HOLIDAYS
