import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
import pandas as pd

from intraday_prices import EASTERN, overlay, require_fresh, session_bars
from send_mail import send_once
from morning_delivery import build_and_publish


class IntradayTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 6, 10, tzinfo=EASTERN)
        self.bars = pd.DataFrame({'Open': [100., 102., 999.], 'High': [103., 105., 999.],
                                  'Low': [99., 101., 999.], 'Close': [102., 104., 999.],
                                  'Volume': [10., 20., 100.]},
                                 index=pd.DatetimeIndex(['2026-10-06 09:30', '2026-10-06 09:59',
                                                        '2026-10-06 10:00'], tz=EASTERN))

    def test_only_completed_today_regular_session_bars(self):
        frame, stamp = session_bars(self.bars, self.now)
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame.Close.iloc[-1], 104)
        self.assertEqual(stamp, pd.Timestamp(self.now))

    def test_old_daily_data_gets_today_snapshot_without_rewriting_history(self):
        idx = pd.DatetimeIndex(['2026-10-05'])
        data = {'spy': pd.DataFrame({'Open': [90.], 'High': [95.], 'Low': [89.],
                                    'Close': [94.], 'Volume': [1000.]}, index=idx),
                'vix': pd.Series([20.], index=idx),
                'fang': pd.DataFrame({'AAPL': [200.]}, index=idx),
                'watch': pd.DataFrame({'AAPL': [200.], 'TSLA': [300.]}, index=idx)}
        previous = data['spy'].copy()
        overlay(data, {'SPY': self.bars, 'AAPL': self.bars}, self.now)
        pd.testing.assert_frame_equal(data['spy'].iloc[:1], previous)
        self.assertEqual(data['spy'].iloc[-1].Close, 104)
        self.assertEqual(data['spy'].iloc[-1].High, 105)
        self.assertEqual(data['spy'].iloc[-1].Volume, 30)
        self.assertEqual(data['fang'].iloc[-1].AAPL, 104)
        self.assertEqual(set(data['price_missing']), {'^VIX', 'TSLA'})
        require_fresh(data['price_stamps']['SPY'], self.now)

    def test_stale_missing_and_future_prices_rejected(self):
        for stamp in ('', '2026-10-05T16:00:00-04:00', '2026-10-06T09:35:00-04:00',
                      '2026-10-06T10:01:00-04:00', '2026-10-06T10:00:00'):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                require_fresh(stamp, self.now)
        with self.assertRaises(ValueError):
            session_bars(self.bars.iloc[:1], self.now)

    def test_after_close_accepts_today_close_not_previous_day(self):
        now = self.now.replace(hour=18)
        require_fresh('2026-10-06T16:00:00-04:00', now)
        with self.assertRaises(ValueError):
            require_fresh('2026-10-05T16:00:00-04:00', now)

    def test_stale_email_never_calls_smtp_or_marks_sent(self):
        env = {'MAIL_FROM': 'a@example.com', 'MAIL_TO': 'b@example.com',
               'MAIL_PASS': 'test-only', 'MAIL_REQUIRE_FRESH': 'true'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            html = root / 'index.html'
            html.write_text('<meta name="price-asof" content="2026-10-05T16:00:00-04:00">')
            smtp = Mock()
            with self.assertRaises(ValueError):
                send_once(env, now=self.now, html_path=html, marker_path=root / 'marker',
                          state_path=root / 'state', smtp_factory=smtp)
            smtp.assert_not_called()
            self.assertFalse((root / 'marker').exists())

    def test_publishing_waits_until_current_snapshot_is_visible(self):
        snapshot = '<meta name="price-asof" content="2026-10-06T09:56:00-04:00">'
        old = Mock(text='<html>yesterday</html>')
        current = Mock(text=snapshot)
        with patch('morning_delivery.Path.read_text', return_value=snapshot), \
             patch('morning_delivery.Path.write_text'), \
             patch('morning_delivery.subprocess.run', return_value=Mock(returncode=0)), \
             patch('requests.get', side_effect=[old, current]) as get, \
             patch('intraday_prices.require_fresh') as fresh, \
             patch('morning_delivery.time.sleep') as sleep:
            build_and_publish()
            self.assertEqual(get.call_count, 2)
            sleep.assert_called_once_with(10)
            fresh.assert_called_once()

    def test_old_public_page_fails_build_instead_of_emailing_old_link(self):
        snapshot = '<meta name="price-asof" content="2026-10-06T09:56:00-04:00">'
        with patch('morning_delivery.Path.read_text', return_value=snapshot), \
             patch('morning_delivery.Path.write_text'), \
             patch('morning_delivery.subprocess.run', return_value=Mock(returncode=0)), \
             patch('requests.get', return_value=Mock(text='old page')), \
             patch('morning_delivery.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'not published yet'):
                build_and_publish()


if __name__ == '__main__':
    unittest.main()
