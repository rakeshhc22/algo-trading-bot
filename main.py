from __future__ import annotations
import time
import json
from pathlib import Path
import re
import pandas as pd
from datetime import datetime, time as datetime_time
from zoneinfo import ZoneInfo

from config import load_credentials, get_reports_directory, get_logs_directory
from config.trading_config import BRDTradingConfig
from utils.logger import configure_logging, get_logger
from utils.helpers import ensure_dirs
from utils.report_generator import generate_comprehensive_report
from trading.execution_engine import run_trading_engine, TradeRecord

LOG = None

def _ensure_dirs() -> None:
    ensure_dirs([get_reports_directory(), get_logs_directory()])

def _summarize_trades(trades: list[TradeRecord]) -> dict:
    total = len(trades)
    total_pnl = sum(t.pnl for t in trades)
    winners = sum(1 for t in trades if t.pnl > 0)
    losers = sum(1 for t in trades if t.pnl < 0)
    win_rate = (winners / total * 100) if total else 0.0
    avg_win = (sum(t.pnl for t in trades if t.pnl > 0) / winners) if winners else 0.0
    avg_loss = (sum(t.pnl for t in trades if t.pnl < 0) / losers) if losers else 0.0
    return {
        "total_trades": total,
        "total_pnl": round(total_pnl, 2),
        "winners": winners,
        "losers": losers,
        "win_rate": round(win_rate, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
    }

def _print_summary(start: float, end: float, summary: dict) -> None:
    duration = end - start
    print("\n" + "=" * 60)
    print("🎯 PERFORMANCE SUMMARY")
    print("=" * 60)
    print(f"⏱️ Duration: {duration:.1f}s")
    print(f"📊 Trades: {summary['total_trades']}")
    print(f"💰 P&L: ₹{summary['total_pnl']:.2f}")
    print(f"📈 Win Rate: {summary['win_rate']:.1f}%")
    print(f"✅ Winners: {summary['winners']} (Avg:₹{summary['avg_win']:.2f})")
    print(f"❌ Losers: {summary['losers']} (Avg:₹{summary['avg_loss']:.2f})")
    if summary['total_pnl'] > 0 and summary['win_rate'] >= 50:
        print("🏆 PROFITABLE SESSION")
    elif summary['total_pnl'] >= 0:
        print("🎯 BREAKEVEN SESSION")
    else:
        print("⚠️ LOSS SESSION")
    print("=" * 60)

def main() -> int:
    global LOG
    start_time = time.time()

    print("=" * 60)
    print("🚀 Z3 STRATEGY BOT - BRD MODE")
    print("=" * 60)

    input_csv = Path("input_data/trading_parameters.csv")
    if not input_csv.exists():
        print("❌ input_data/trading_parameters.csv missing.")
        return 1

    # Load the correct symbol map from JSON file
    symbol_map_file = Path("config/symbol_map.json")
    if not symbol_map_file.exists():
        print("❌ config/symbol_map.json missing.")
        return 1
    
    try:
        with open(symbol_map_file, 'r') as f:
            symbol_map = json.load(f)
        print(f"📋 Loaded symbol map: {symbol_map}")
    except Exception as e:
        print(f"❌ Failed to load symbol map: {e}")
        return 1

    df = pd.read_csv(input_csv)
    required_cols = ["SL_NO","SCRIPT_LIST","STOP_LOSS_PERCENT","NO_OF_SHARES","ENTRY_TIME","EXIT_TIME"]
    if any(col not in df.columns for col in required_cols):
        print("❌ Input CSV missing required columns")
        return 1

    time_pattern = re.compile(r"^\d{2}:\d{2}:\d{2}$")
    if not all(time_pattern.match(t) for t in df["ENTRY_TIME"]) or not all(time_pattern.match(t) for t in df["EXIT_TIME"]):
        print("❌ Time columns ENTRY_TIME or EXIT_TIME have invalid format")
        return 1

    symbols = [s.strip().upper() for s in df["SCRIPT_LIST"]]
    stop_loss_fraction = float(df["STOP_LOSS_PERCENT"].iloc[0])/100
    quantity = int(df["NO_OF_SHARES"].iloc[0])
    h,m,s = map(int, df["ENTRY_TIME"].iloc[0].split(":"))
    entry_time = datetime_time(h,m,s)
    h,m,s = map(int, df["EXIT_TIME"].iloc[0].split(":"))
    exit_time = datetime_time(h,m,s)
    tz = ZoneInfo("Asia/Kolkata")

    # Validate that all symbols from CSV exist in symbol_map
    missing_symbols = [sym for sym in symbols if sym not in symbol_map]
    if missing_symbols:
        print(f"❌ Symbols not found in symbol_map.json: {missing_symbols}")
        return 1

    config = BRDTradingConfig(
        symbols=symbols,
        stop_loss_fraction=stop_loss_fraction,
        quantity_per_trade=quantity,
        entry_time=entry_time,
        exit_time=exit_time,
        timezone=tz,
        symbol_map=symbol_map,  # Use the correct symbol map from JSON
    )

    _ensure_dirs()
    configure_logging(logs_dir=get_logs_directory())
    LOG = get_logger(__name__)
    LOG.info("Starting Z3 Strategy with BRD configuration")
    
    creds = load_credentials()
    LOG.info("API credentials loaded")

    try:
        result = run_trading_engine(config)
    except Exception as exc:
        LOG.exception(f"Error running trading engine: {exc}")
        return 1

    trades = result.get("trades", [])

    LOG.info(f"Trading session completed with {len(trades)} trades")

    try:
        rpt = generate_comprehensive_report(trades, out_dir=get_reports_directory())
        print(f"\n📊 Report generated at: {rpt}")
    except Exception as e:
        LOG.exception(f"Failed to generate report: {e}")

    summary = _summarize_trades(trades)
    end_time = time.time()
    _print_summary(start_time, end_time, summary)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())