"""
Strategy package for Z3.

Exports:
- enums & dataclasses for signals and trade plans
- signal generator to decide LONG / SHORT
- Z3Strategy: core logic to build trade plan and evaluate exits/SL
"""

from .signal_generator import (
    SignalSide,
    Signal,
    generate_signal,
)

from .z3_strategy import (
    TradePlan,
    TradeExitDecision,
    Z3Strategy,
)

__all__ = [
    "SignalSide",
    "Signal",
    "generate_signal",
    "TradePlan",
    "TradeExitDecision",
    "Z3Strategy",
]
