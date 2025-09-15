import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from data.market_data import MarketDataFetcher, Candle
from data.dhan_api import DhanAPI


class DummyAPI:
     
    def __init__(self, candles):
        self._candles = candles

    def get_historical_candles(self, symbol, exchange_segment, instrument_type, interval, from_date, to_date):
        return self._candles


def make_candle_dict(dt_str, open_, high, low, close, volume):
    date, t = dt_str.split(" ")
    return {
        "date": date,
        "time": t,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def test_fetch_intraday_candles_parsing():
    raw = [
        make_candle_dict("2025-08-21 09:24:00", 100, 101, 99, 100.5, 1000),
        make_candle_dict("2025-08-21 09:25:00", 101, 102, 100, 101.5, 2000),
    ]
    api = DummyAPI(raw)
    fetcher = MarketDataFetcher(api, exchange="NSE", instrument="CM")
    candles = fetcher.fetch_intraday_candles("BAJFINANCE", datetime(2025, 8, 21))
    assert len(candles) == 2
    assert isinstance(candles[0], Candle)
    assert candles[0].close == 100.5


def test_get_entry_price_and_yday_close():
    today_raw = [
        make_candle_dict("2025-08-21 09:24:00", 100, 101, 99, 100.5, 1000),
    ]
    yday_raw = [
        make_candle_dict("2025-08-20 15:29:00", 200, 201, 199, 200.5, 1500),
    ]

    class YdayTodayAPI:
        def get_historical_candles(self, symbol, exchange_segment, instrument_type, interval, from_date, to_date):
            if from_date == "2025-08-21":
                return today_raw
            elif from_date == "2025-08-20":
                return yday_raw
            return []

    fetcher = MarketDataFetcher(YdayTodayAPI(), exchange="NSE", instrument="CM")
    today_dt = datetime(2025, 8, 21, tzinfo=ZoneInfo("Asia/Kolkata"))

    entry_price = fetcher.get_entry_price("BAJFINANCE", today_dt)
    yday_close = fetcher.get_yesterdays_close("BAJFINANCE", today_dt)

    assert entry_price == 100.5
    assert yday_close == 200.5
