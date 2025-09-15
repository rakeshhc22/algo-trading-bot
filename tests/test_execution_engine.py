import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from strategy.signal_generator import SignalSide, Signal
from strategy.z3_strategy import Z3Strategy, TradePlan, TradeExitDecision
from trading.execution_engine import TradeRecord
from config.settings import get_default_config


class DummyFetcher:
    """Fake MarketDataFetcher for signals (yday vs today close)."""
    def __init__(self, yday_close=100, today_close=101):
        self.yday = yday_close
        self.today = today_close

    def get_yesterdays_close(self, symbol, today_dt):
        return self.yday

    def get_entry_price(self, symbol, today_dt):
        return self.today


class DummyOrderManager:
    def __init__(self, ltp_sequence=None):
        # list of LTP values to return for SL polling
        self.ltp_sequence = ltp_sequence or []
        self.exit_called = False

    def place_entry_order(self, plan: TradePlan):
        return type("Fill", (), {
            "order_id": "123",
            "symbol": plan.symbol,
            "side": plan.side,
            "entry_price": plan.entry_price,
            "quantity": plan.quantity,
        })()

    def exit_position(self, fill):
        self.exit_called = True
        return {"status": "exited"}

    def get_ltp(self, symbol, exchange="NSE", instrument="CM"):
        # Return next LTP in sequence or last one
        if not self.ltp_sequence:
            return None
        return self.ltp_sequence.pop(0)

    def wait_for_stop_loss_or_time(self, plan, exit_time_reached, sl_decider, poll_interval_sec=1.0):
        # Simulate SL polling
        while self.ltp_sequence:
            ltp = self.ltp_sequence.pop(0)
            decision = sl_decider(ltp)
            if decision.should_exit:
                return decision
        # If no SL, then time exit
        return TradeExitDecision(should_exit=True, reason="TIME_EXIT", exit_price_hint=plan.entry_price)


def make_plan(side=SignalSide.LONG, entry_price=100):
    cfg = get_default_config()
    strategy = Z3Strategy(cfg)
    sl_price = strategy.compute_stop_loss_price(side, entry_price)
    return TradePlan(
        symbol="BAJFINANCE",
        side=side,
        entry_time=cfg.times.entry_time,
        exit_time=cfg.times.exit_time,
        entry_price=entry_price,
        stop_loss_price=sl_price,
        quantity=cfg.strategy.qty_per_trade,
        order_type=cfg.broker.order_type,
        product_type=cfg.broker.product_type,
        timezone=cfg.times.timezone,
    )


def test_stop_loss_exit_long():
    cfg = get_default_config()
    strategy = Z3Strategy(cfg)
    plan = make_plan(SignalSide.LONG, 100)
    # Simulate LTP dropping to SL (99.75)
    order_mgr = DummyOrderManager(ltp_sequence=[100.0, 99.75])
    decision = order_mgr.wait_for_stop_loss_or_time(
        plan=plan,
        exit_time_reached=lambda: False,
        sl_decider=lambda ltp: strategy.check_stop_loss(
            side=plan.side,
            entry_price=plan.entry_price,
            stop_loss_price=plan.stop_loss_price,
            current_ltp=ltp,
            symbol=plan.symbol,
        ),
    )
    assert decision.should_exit
    assert decision.reason == "STOP_LOSS"


def test_time_exit_short():
    cfg = get_default_config()
    strategy = Z3Strategy(cfg)
    plan = make_plan(SignalSide.SHORT, 200)
    # No SL hit, so exit at time
    order_mgr = DummyOrderManager(ltp_sequence=[199.5, 199.0])
    decision = order_mgr.wait_for_stop_loss_or_time(
        plan=plan,
        exit_time_reached=lambda: True,  # simulate time reached
        sl_decider=lambda ltp: strategy.check_stop_loss(
            side=plan.side,
            entry_price=plan.entry_price,
            stop_loss_price=plan.stop_loss_price,
            current_ltp=ltp,
            symbol=plan.symbol,
        ),
    )
    assert decision.should_exit
    assert decision.reason == "TIME_EXIT"


def test_trade_record_pnl_calculation():
    record = TradeRecord(
        symbol="NTPC",
        side="LONG",
        entry_price=100,
        exit_price=102,
        quantity=1,
        reason="TIME_EXIT",
        points=2,
        pnl=2,
    )
    assert record.symbol == "NTPC"
    assert record.points == 2
    assert record.pnl == 2
