"""Use timestamped regular-session minute bars instead of assuming daily freshness."""
from datetime import timedelta
from zoneinfo import ZoneInfo
import pandas as pd

EASTERN = ZoneInfo('America/New_York')
CENTRAL = ZoneInfo('America/Chicago')
MAX_AGE_MINUTES = 20


def session_bars(frame, now):
    now = now.astimezone(EASTERN)
    if frame.empty or frame.index.tz is None:
        raise ValueError('Missing timestamped minute prices')
    frame = frame.copy()
    frame.index = frame.index.tz_convert(EASTERN)
    minute = frame.index.hour * 60 + frame.index.minute
    frame = frame.loc[(frame.index.date == now.date()) & (minute >= 570) &
                      (minute < 960) & (frame.index + pd.Timedelta(minutes=1) <= now)]
    frame = frame.dropna(subset=['Open', 'High', 'Low', 'Close']).sort_index()
    if frame.empty:
        raise ValueError('No completed minute bar from today')
    stamp = frame.index[-1] + pd.Timedelta(minutes=1)
    reference = min(now, now.replace(hour=16, minute=0, second=0, microsecond=0))
    if reference - stamp > timedelta(minutes=MAX_AGE_MINUTES):
        raise ValueError('Minute price is more than 20 minutes behind')
    return frame, stamp


def overlay(data, quotes, now):
    """quotes maps ticker to one-minute OHLC. Preserve history and label missing data."""
    stamps, missing = {}, []
    tickers = list(dict.fromkeys(['SPY', '^VIX', *data['fang'].columns, *data['watch'].columns]))
    for ticker in tickers:
        try:
            frame, stamp = session_bars(quotes.get(ticker, pd.DataFrame()), now)
        except ValueError:
            missing.append(ticker)
            continue
        day = pd.Timestamp(now.astimezone(EASTERN).date())
        close = float(frame['Close'].iloc[-1])
        if ticker == 'SPY':
            row = {column: 0.0 for column in data['spy'].columns}
            row.update(Open=float(frame['Open'].iloc[0]), High=float(frame['High'].max()),
                       Low=float(frame['Low'].min()), Close=close,
                       Volume=float(frame['Volume'].sum()) if 'Volume' in frame else 0.0)
            data['spy'].loc[day] = row
            data['spy'] = data['spy'].sort_index()
        if ticker == '^VIX':
            data['vix'].loc[day] = close
            data['vix'] = data['vix'].sort_index()
        for key in ('fang', 'watch'):
            if ticker in data[key].columns:
                data[key].loc[day, ticker] = close
        stamps[ticker] = stamp.isoformat()
    data['price_stamps'] = stamps
    data['price_missing'] = missing
    return data


def require_fresh(stamp, now):
    if not stamp:
        raise ValueError('No verified current-session SPY price; retry data collection')
    ts = pd.Timestamp(stamp)
    now = now.astimezone(EASTERN)
    if ts.tzinfo is None or ts.tz_convert(EASTERN).date() != now.date() or ts > now:
        raise ValueError('Price date is not today or timestamp is invalid')
    reference = min(now, now.replace(hour=16, minute=0, second=0, microsecond=0))
    if reference - ts > timedelta(minutes=MAX_AGE_MINUTES):
        raise ValueError('Price is too old; retry instead of sending yesterday\'s briefing')
