from dataclasses import dataclass
from datetime import time
from typing import Dict, List
from zoneinfo import ZoneInfo

@dataclass
class BRDTradingConfig:
    symbols: List[str]
    stop_loss_fraction: float
    quantity_per_trade: int
    entry_time: time
    exit_time: time
    timezone: ZoneInfo
    symbol_map: Dict[str, str]
    exchange: str = "NSE_EQ"
    instrument: str = "EQUITY"
    order_type: str = "MARKET"
    product_type: str = "INTRADAY"
