from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import datetime, time as datetime_time
from typing import Dict, List, Set
from time import sleep
from zoneinfo import ZoneInfo
import logging
import os

from config import load_credentials
from data.dhan_api import DhanAPI
from data.market_data import MarketDataFetcher
from strategy import Z3Strategy, generate_signal, SignalSide
from trading.order_manager import OrderManager, OrderFill

logger = logging.getLogger(__name__)

@dataclass
class TradeRecord:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: int
    reason: str
    points: float
    pnl: float

@dataclass
class BRDTradingConfig:
    symbols: List[str]
    stop_loss_fraction: float
    quantity_per_trade: int
    entry_time: datetime_time
    exit_time: datetime_time
    timezone: ZoneInfo
    symbol_map: Dict[str, str]
    exchange: str = "NSE_EQ"
    instrument: str = "EQUITY"
    order_type: str = "MARKET"
    product_type: str = "INTRADAY"

def _now_ist(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)

def clear_screen():
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')

def print_header():
    print("=" * 60)
    print("🚀 Z3 STRATEGY BOT - BRD COMPLIANT LIVE TRADING")
    print("=" * 60)

def print_status(msg: str, level: str = "INFO"):
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "ERROR": "❌"}
    icon = icons.get(level, "ℹ️")
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {icon} {msg}")

def print_position_summary(open_fills: Dict[str, OrderFill]):
    if not open_fills:
        return
    print("\n" + "─" * 50)
    print("📊 ACTIVE POSITIONS")
    print("─" * 50)
    for sym, fill in open_fills.items():
        print(f" {sym}: {fill.side.name} @ ₹{fill.entry_price:.2f} (Qty: {fill.quantity})")
    print("─" * 50)


def calculate_precise_stop_loss(side: SignalSide, entry_price: float, stop_loss_fraction: float) -> float:
    if side == SignalSide.LONG:
        return round(entry_price * (1 - stop_loss_fraction), 2)
    else:
        return round(entry_price * (1 + stop_loss_fraction), 2)

def is_stop_loss_hit(side: SignalSide, entry_price: float, stop_loss_price: float, current_ltp: float) -> bool:
    if side == SignalSide.LONG:
        return current_ltp <= stop_loss_price
    else:
        return current_ltp >= stop_loss_price

def calculate_pnl(side: SignalSide, entry_price: float, exit_price: float, quantity: int) -> tuple[float, float]:
    points = exit_price - entry_price if side == SignalSide.LONG else entry_price - exit_price
    pnl = points * quantity
    return round(points, 2), round(pnl, 2)

def run_trading_engine(config: BRDTradingConfig) -> Dict[str, List[TradeRecord]]:
    clear_screen()
    print_header()
    if config is None:
        raise ValueError("A valid BRDTradingConfig is required")

    creds = load_credentials()
    tz = config.timezone
    today = _now_ist(tz).replace(hour=0, minute=0, second=0, microsecond=0)

    missing_syms = [s for s in config.symbols if s.upper() not in config.symbol_map]
    if missing_syms:
        raise ValueError(f"Missing symbol IDs for: {', '.join(missing_syms)}")

    print_status("BRD Configuration Loaded")
    print_status(f"Symbols: {', '.join(config.symbols)}")
    print_status(f"Stop-Loss: {config.stop_loss_fraction*100:.2f}%")
    print_status(f"Quantity: {config.quantity_per_trade}")
    print_status(f"Entry: {config.entry_time} | Exit: {config.exit_time}")

    api = DhanAPI(access_token=creds.access_token, client_id=creds.client_id)
    
    try:
        if api.connect_live_feed():
            print_status("WebSocket feed connected - real-time monitoring enabled", "SUCCESS")
        else:
            print_status("Using REST API fallback for price monitoring", "INFO")
    except Exception:
        print_status("Using REST API fallback for price monitoring", "INFO")

    fetcher = MarketDataFetcher(api, config.symbol_map, config.exchange, config.instrument)
    strategy = Z3Strategy(config)
    order_mgr = OrderManager(api, config.symbol_map, config.exchange)

    open_fills = {}
    stopped_out_symbols = set()
    results = []

    def is_entry_time() -> bool:
        now = _now_ist(tz)
        t = config.entry_time
        return (now.hour, now.minute, now.second) == (t.hour, t.minute, t.second)

    def is_exit_time() -> bool:
        now = _now_ist(tz)
        t = config.exit_time
        return (now.hour, now.minute, now.second) >= (t.hour, t.minute, t.second)

    def is_market_open() -> bool:
        now = _now_ist(tz)
        current_time = (now.hour, now.minute)
        return (9, 15) <= current_time <= (15, 30)

    if not is_market_open():
        print_status("Market closed. Waiting for market open at 09:15...", "WARNING")
        while not is_market_open():
            sleep(30)

    print_status(f"Market open. Waiting for BRD entry time: {config.entry_time}")
    while not is_entry_time():
        now = _now_ist(tz)
        entry_dt = now.replace(hour=config.entry_time.hour, minute=config.entry_time.minute, second=config.entry_time.second)
        if entry_dt < now:
            entry_dt = entry_dt.replace(day=entry_dt.day + 1)
        time_left = (entry_dt - now).total_seconds()
        if time_left <= 60 and int(time_left) % 10 == 0:
            print_status(f"BRD entry in {int(time_left)} seconds...")
        sleep(1)

    print_status("🎯 BRD ENTRY TIME HIT! Processing signals...", "SUCCESS")
    print("\n" + "─" * 50)
    print("📈 BRD SIGNAL GENERATION")
    print("─" * 50)

    for symbol in config.symbols:
        try:
            if symbol in stopped_out_symbols:
                print_status(f"{symbol}: Skipped - stop-loss already hit today", "WARNING")
                continue
                
            print_status(f"Processing {symbol}...")
            sig = generate_signal(fetcher, symbol, today_dt=today)
            
            if sig.side == SignalSide.NONE or sig.entry_ref_price is None:
                print_status(f"{symbol}: No signal generated", "WARNING")
                continue
                
            plan = strategy.build_trade_plan(sig)
            if plan is None:
                print_status(f"{symbol}: Trade plan rejected", "WARNING")
                continue
            
            # Create a new plan with updated quantity instead of assigning to immutable field
            updated_plan = replace(
                plan,
                quantity=config.quantity_per_trade,
                order_type=config.order_type
            )
            
            fill = order_mgr.place_entry_order(updated_plan)
            open_fills[symbol] = fill

            if hasattr(api, 'is_feed_connected') and api.is_feed_connected:
                sid = config.symbol_map[symbol.upper()]
                if hasattr(api, 'subscribe_to_price_updates'):
                    try:
                        api.subscribe_to_price_updates(sid)
                    except Exception:
                        pass

            print_status(f"{symbol}: {fill.side.name} order placed @ ₹{fill.entry_price:.2f}", "SUCCESS")
            
        except Exception as e:
            print_status(f"{symbol}: Error in order placement or signal generation: {e}", "ERROR")
            logger.exception(f"Detailed error for {symbol}")

    if not open_fills:
        print_status("No positions opened. Session complete.", "WARNING")
        try:
            api.disconnect_websockets()
        except Exception:
            pass
        return {"trades": results}

    print_position_summary(open_fills)
    print_status(f"🔍 Monitoring {len(open_fills)} positions for BRD stop-loss...", "SUCCESS")

    monitoring_cycle = 0

    while open_fills and not is_exit_time():
        monitoring_cycle += 1
        symbols_to_check = list(open_fills.keys())
        current_prices = order_mgr.get_multiple_ltps_optimized(symbols_to_check)
        symbols_to_remove = []

        for symbol, fill in open_fills.items():
            if symbol in stopped_out_symbols:
                symbols_to_remove.append(symbol)
                continue
                
            current_ltp = current_prices.get(symbol)
            if current_ltp is None:
                continue

            sl_price = calculate_precise_stop_loss(fill.side, fill.entry_price, config.stop_loss_fraction)

            if is_stop_loss_hit(fill.side, fill.entry_price, sl_price, current_ltp):
                print_status(f"{symbol}: Stop-loss hit at LTP ₹{current_ltp:.2f} (SL: ₹{sl_price:.2f})", "WARNING")
                try:
                    order_mgr.exit_position(fill)
                    points, pnl = calculate_pnl(fill.side, fill.entry_price, current_ltp, fill.quantity)
                    results.append(TradeRecord(symbol, fill.side.name, fill.entry_price, current_ltp, fill.quantity, "STOP_LOSS", points, pnl))
                    print_status(f"{symbol}: Exited with P&L ₹{pnl:.2f} (Points: {points:.2f})", "SUCCESS" if pnl >= 0 else "WARNING")
                    stopped_out_symbols.add(symbol)
                    symbols_to_remove.append(symbol)
                except Exception as e:
                    print_status(f"{symbol}: Exit failed: {e}", "ERROR")
                    logger.exception(f"Exit error for {symbol}")
                    stopped_out_symbols.add(symbol)
                    symbols_to_remove.append(symbol)

        for sym in symbols_to_remove:
            if sym in open_fills:
                try:
                    if hasattr(api, 'unsubscribe_from_price_updates') and api.is_feed_connected:
                        sid = config.symbol_map[sym.upper()]
                        api.unsubscribe_from_price_updates(sid)
                except Exception:
                    pass
                del open_fills[sym]

        if monitoring_cycle % 30 == 0:
            active = ", ".join(open_fills.keys())
            stopped = ", ".join(stopped_out_symbols)
            status = f"Active: {active}" if active else ""
            if stopped:
                status = f"{status} | Stopped: {stopped}"
            if status:
                print_status(status, "INFO")

        sleep(1.0 if (hasattr(api, 'is_feed_connected') and api.is_feed_connected) else 2.0)

    if open_fills:
        print_status("Exit time reached. Closing remaining positions...", "WARNING")
        final_prices = order_mgr.get_multiple_ltps_optimized(list(open_fills.keys()))
        for sym in list(open_fills.keys()):
            try:
                fill = open_fills[sym]
                last_price = final_prices.get(sym) or fill.entry_price
                order_mgr.exit_position(fill)
                points, pnl = calculate_pnl(fill.side, fill.entry_price, last_price, fill.quantity)
                results.append(TradeRecord(sym, fill.side.name, fill.entry_price, last_price, fill.quantity, "END_OF_DAY", points, pnl))
                print_status(f"{sym}: End-of-day exit with P&L ₹{pnl:.2f} (Points {points:.2f})", "SUCCESS" if pnl >= 0 else "WARNING")
            except Exception as e:
                print_status(f"{sym}: EOD exit failed: {e}", "ERROR")
                logger.exception(f"EOD exit error for {sym}")

    print_status("Trading session complete", "SUCCESS")

    # Summary
    total_pnl = sum(r.pnl for r in results)
    total_points = sum(r.points for r in results)
    wins = len([r for r in results if r.pnl > 0])
    losses = len([r for r in results if r.pnl < 0])

    print("\n" + "─" * 50)
    print("📊 SESSION SUMMARY")
    print("─" * 50)
    print(f"Trades: {len(results)} | Points: {total_points:.2f} | P&L: ₹{total_pnl:.2f}")
    print(f"Winners: {wins} | Losers: {losses}")
    if stopped_out_symbols:
        print(f"Stopped Out Symbols: {', '.join(sorted(stopped_out_symbols))}")

    # Compliance check
    trade_counts = {}
    for t in results:
        trade_counts[t.symbol] = trade_counts.get(t.symbol,0) + 1
    compliant = True
    print("\nBRD Compliance Check:")
    for s in config.symbols:
        count = trade_counts.get(s, 0)
        status = "✅" if count <= 1 else "❌"
        print(f" {s}: {count} trade(s) {status}")
        if count > 1:
            compliant = False
    print(f"Overall BRD Compliance: {'✅ COMPLIANT' if compliant else '❌ VIOLATION'}")
    print("─" * 50)

    try:
        api.disconnect_websockets()
    except Exception:
        pass

    return {"trades": results}