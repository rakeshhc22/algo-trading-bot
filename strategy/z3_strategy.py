from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional, Set
from zoneinfo import ZoneInfo
from config.trading_config import BRDTradingConfig
from .signal_generator import Signal, SignalSide

@dataclass(frozen=True)
class TradePlan:
    symbol: str
    side: SignalSide
    entry_time: time
    exit_time: time
    entry_price: float
    stop_loss_price: float
    quantity: int
    order_type: str
    product_type: str
    timezone: ZoneInfo

@dataclass(frozen=True)
class TradeExitDecision:
    should_exit: bool
    reason: str
    exit_price_hint: Optional[float] = None

class Z3Strategy:
    def __init__(self, config: BRDTradingConfig) -> None:
        self.config = config
        self.sl_hit_symbols: Set[str] = set()

    def compute_stop_loss_price(self, side: SignalSide, entry_price: float) -> float:
        sl_frac = self.config.stop_loss_fraction
        if side == SignalSide.LONG:
            return round(entry_price * (1 - sl_frac), 2)
        elif side == SignalSide.SHORT:
            return round(entry_price * (1 + sl_frac), 2)
        raise ValueError("Side cannot be NONE")

    def is_entry_time(self, now: datetime) -> bool:
        t = self.config.entry_time
        return (now.hour, now.minute, now.second) == (t.hour, t.minute, t.second)

    def is_exit_time(self, now: datetime) -> bool:
        t = self.config.exit_time
        return (now.hour, now.minute, now.second) >= (t.hour, t.minute, t.second)

    def build_trade_plan(self, signal: Signal) -> Optional[TradePlan]:
        if signal.side == SignalSide.NONE or signal.entry_ref_price is None:
            return None
        symbol = signal.symbol.upper()
        if symbol in self.sl_hit_symbols:
            return None  # no re-entry same day once SL hit
        entry_price = signal.entry_ref_price
        stop_loss_price = self.compute_stop_loss_price(signal.side, entry_price)
        return TradePlan(
            symbol=symbol,
            side=signal.side,
            entry_time=self.config.entry_time,
            exit_time=self.config.exit_time,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            quantity=self.config.quantity_per_trade,
            order_type=self.config.order_type,
            product_type=self.config.product_type,
            timezone=self.config.timezone,
        )

    def check_stop_loss(self, side: SignalSide, entry_price: float, stop_loss_price: float, current_ltp: float, symbol: str) -> TradeExitDecision:
        if side == SignalSide.LONG and current_ltp <= stop_loss_price:
            self.sl_hit_symbols.add(symbol.upper())
            return TradeExitDecision(True, "STOP_LOSS", exit_price_hint=current_ltp)
        elif side == SignalSide.SHORT and current_ltp >= stop_loss_price:
            self.sl_hit_symbols.add(symbol.upper())
            return TradeExitDecision(True, "STOP_LOSS", exit_price_hint=current_ltp)
        return TradeExitDecision(False, "NONE")

    def check_time_exit(self, now: datetime) -> TradeExitDecision:
        if self.is_exit_time(now):
            return TradeExitDecision(True, "TIME_EXIT")
        return TradeExitDecision(False, "NONE")

    @staticmethod
    def points(side: SignalSide, entry_price: float, exit_price: float) -> float:
        if side == SignalSide.LONG:
            return round(exit_price - entry_price, 2)
        elif side == SignalSide.SHORT:
            return round(entry_price - exit_price, 2)
        return 0.0

    @staticmethod
    def pnl_amount(points: float, quantity: int) -> float:
        return round(points * quantity, 2)

    def reset_daily_state(self) -> None:
        self.sl_hit_symbols.clear()
