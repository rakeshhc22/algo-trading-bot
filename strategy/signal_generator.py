from __future__ import annotations

from enum import Enum, auto
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class SignalSide(Enum):
    NONE = auto()
    LONG = auto()
    SHORT = auto()

class Signal:
    def __init__(self, symbol: str, side: SignalSide, entry_ref_price: Optional[float] = None):
        self.symbol = symbol
        self.side = side
        self.entry_ref_price = entry_ref_price

def generate_signal(fetcher, symbol: str, today_dt: datetime) -> Signal:
    logger.info(f"Generating signal for {symbol} on {today_dt.date()}")

    yesterday_close = None
    try:
        yesterday_close = fetcher.get_yesterdays_close_1529(symbol, today_dt)
    except Exception as e:
        logger.warning(f"Couldn't get yesterday's close for {symbol}: {e}")

    today_price = None
    try:
        today_price = fetcher.get_todays_entry_price_0924(symbol, today_dt)
    except Exception as e:
        logger.warning(f"Couldn't get today's entry price for {symbol}: {e}")

    logger.info(f"{symbol}: Yesterday's close = {yesterday_close}")
    logger.info(f"{symbol}: Today's entry reference price = {today_price}")

    if yesterday_close is None or today_price is None:
        logger.warning(f"{symbol}: NO signal (missing data)")
        return Signal(symbol, SignalSide.NONE)

    if today_price > yesterday_close:
        logger.info(f"{symbol}: LONG signal")
        return Signal(symbol, SignalSide.LONG, today_price)
    elif today_price < yesterday_close:
        logger.info(f"{symbol}: SHORT signal")
        return Signal(symbol, SignalSide.SHORT, today_price)
    else:
        logger.info(f"{symbol}: NO signal (prices equal)")
        return Signal(symbol, SignalSide.NONE)
