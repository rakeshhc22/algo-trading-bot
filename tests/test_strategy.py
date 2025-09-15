import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from strategy.signal_generator import SignalSide, generate_signal, Signal
from strategy.z3_strategy import Z3Strategy
from config.settings import get_default_config


class DummyFetcher:
    """
    Fake MarketDataFetcher to simulate yesterday and today closes.
    """
    def __init__(self, yday_close=None, today_close=None):
        self._yday = yday_close
        self._today = today_close

    def get_yesterdays_close(self, symbol, today_dt):
        return self._yday

    def get_entry_price(self, symbol, today_dt):
        return self._today


def test_generate_signal_long():
    fetcher = DummyFetcher(yday_close=100, today_close=101)
    sig = generate_signal(fetcher, "BAJFINANCE", datetime.now())
    assert sig.side == SignalSide.LONG
    assert sig.entry_ref_price == 101


def test_generate_signal_short():
    fetcher = DummyFetcher(yday_close=200, today_close=199)
    sig = generate_signal(fetcher, "HCLTECH", datetime.now())
    assert sig.side == SignalSide.SHORT


def test_generate_signal_none_equal_prices():
    fetcher = DummyFetcher(yday_close=150, today_close=150)
    sig = generate_signal(fetcher, "NTPC", datetime.now())
    assert sig.side == SignalSide.NONE


def test_stop_loss_long_hit():
    cfg = get_default_config()
    strategy = Z3Strategy(cfg)
    entry_price = 100.0
    sl_price = strategy.compute_stop_loss_price(SignalSide.LONG, entry_price)
    # LTP <= SL triggers exit
    decision = strategy.check_stop_loss(SignalSide.LONG, entry_price, sl_price, current_ltp=sl_price, symbol="BAJFINANCE")
    assert decision.should_exit
    assert decision.reason == "STOP_LOSS"


def test_stop_loss_short_hit():
    cfg = get_default_config()
    strategy = Z3Strategy(cfg)
    entry_price = 100.0
    sl_price = strategy.compute_stop_loss_price(SignalSide.SHORT, entry_price)
    # LTP >= SL triggers exit
    decision = strategy.check_stop_loss(SignalSide.SHORT, entry_price, sl_price, current_ltp=sl_price, symbol="HCLTECH")
    assert decision.should_exit
    assert decision.reason == "STOP_LOSS"


def test_points_and_pnl_calculation():
    pts = Z3Strategy.points(SignalSide.LONG, 100, 102)
    assert pts == 2
    pnl = Z3Strategy.pnl_amount(pts, 1)
    assert pnl == 2

    pts2 = Z3Strategy.points(SignalSide.SHORT, 200, 190)
    assert pts2 == 10
    pnl2 = Z3Strategy.pnl_amount(pts2, 1)
    assert pnl2 == 10
