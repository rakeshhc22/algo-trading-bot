from pathlib import Path
from typing import Iterable, Any, Mapping, List
import pandas as pd
from datetime import datetime
import json
import logging

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

logger = logging.getLogger(__name__)

def _safe_round(value: Any, digits: int = 2) -> float:
    try:
        return round(float(value or 0), digits)
    except Exception:
        return 0.0

def _normalize_trade(tr: Any) -> Mapping[str, Any]:
    if isinstance(tr, Mapping):
        data = tr
    else:
        data = {
            "symbol": getattr(tr, "symbol", ""),
            "side": getattr(tr, "side", ""),
            "entry_price": getattr(tr, "entry_price", 0.0),
            "exit_price": getattr(tr, "exit_price", 0.0),
            "quantity": getattr(tr, "quantity", 0),
            "reason": getattr(tr, "reason", ""),
            "points": getattr(tr, "points", 0.0),
            "pnl": getattr(tr, "pnl", 0.0),
        }
    data["entry_price"] = _safe_round(data.get("entry_price", 0))
    data["exit_price"] = _safe_round(data.get("exit_price", 0))
    data["points"] = _safe_round(data.get("points", 0))
    data["pnl"] = _safe_round(data.get("pnl", 0))
    data["quantity"] = int(data.get("quantity") or 0)
    data["symbol"] = str(data.get("symbol", "")).upper()
    data["side"] = str(data.get("side", "")).upper()
    data["reason"] = str(data.get("reason", ""))
    return data

def _calculate_metrics(df: pd.DataFrame) -> dict:
    if df.empty or "pnl" not in df.columns:
        return {
            "total_trades": 0, "total_pnl": 0, "winners": 0, "losers": 0,
            "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "profit_factor": 0.0,
            "max_profit": 0.0, "max_loss": 0.0, "avg_points": 0.0,
        }
    total_trades = len(df)
    total_pnl = _safe_round(df["pnl"].sum())
    winners = df[df["pnl"] > 0]
    losers = df[df["pnl"] < 0]
    win_rate = _safe_round((len(winners) / total_trades * 100) if total_trades > 0 else 0)
    avg_win = _safe_round(winners["pnl"].mean() if len(winners) > 0 else 0)
    avg_loss = _safe_round(abs(losers["pnl"].mean()) if len(losers) > 0 else 0)
    total_wins = winners["pnl"].sum() if len(winners) > 0 else 0
    total_losses = abs(losers["pnl"].sum()) if len(losers) > 0 else 1
    profit_factor = _safe_round(total_wins / total_losses if total_losses > 0 else 0)
    max_profit = _safe_round(df["pnl"].max())
    max_loss = _safe_round(df["pnl"].min())
    avg_points = _safe_round(df["points"].mean() if "points" in df.columns else 0)
    return dict(
        total_trades=total_trades, total_pnl=total_pnl, winners=len(winners),
        losers=len(losers), win_rate=win_rate, avg_win=avg_win, avg_loss=avg_loss,
        profit_factor=profit_factor, max_profit=max_profit, max_loss=max_loss,
        avg_points=avg_points,
    )

def generate_comprehensive_report(trades: Iterable[Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [_normalize_trade(t) for t in trades]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["symbol", "side", "entry_price", "exit_price", "quantity", "reason", "points", "pnl"])
    metrics = _calculate_metrics(df)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename_base = f"{datetime.now().strftime('%Y-%m-%d')}_Z3_Strategy_Report_{timestamp}"
    excel_path = out_dir / f"{filename_base}.xlsx"
    csv_path = out_dir / f"{filename_base}.csv"
    df.to_csv(csv_path, index=False)
    if HAS_OPENPYXL:
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            summary = [
                ["Z3 STRATEGY TRADING REPORT", ""],
                ["Report Date", datetime.now().strftime("%Y-%m-%d")],
                ["Report Time", datetime.now().strftime("%H:%M:%S IST")],
                [],
                ["PERFORMANCE SUMMARY", ""],
                ["Total Trades", metrics["total_trades"]],
                ["Total P&L (₹)", metrics["total_pnl"]],
                ["Win Rate (%)", metrics["win_rate"]],
                ["Winners", metrics["winners"]],
                ["Losers", metrics["losers"]],
                [],
                ["DETAILED METRICS", ""],
                ["Average Win (₹)", metrics["avg_win"]],
                ["Average Loss (₹)", metrics["avg_loss"]],
                ["Profit Factor", metrics["profit_factor"]],
                ["Maximum Profit (₹)", metrics["max_profit"]],
                ["Maximum Loss (₹)", metrics["max_loss"]],
                ["Average Points", metrics["avg_points"]],
            ]
            pd.DataFrame(summary, columns=["Metric", "Value"]).to_excel(writer, sheet_name="Executive Summary", index=False)

            if not df.empty:
                df["Result"] = df["pnl"].apply(lambda x: "WIN" if x > 0 else "LOSS" if x < 0 else "BREAKEVEN")
                df.rename(columns={
                    "symbol": "Symbol", "side": "Side", "entry_price": "Entry Price", "exit_price": "Exit Price",
                    "quantity": "Quantity", "points": "Points", "pnl": "P&L", "reason": "Reason"
                }, inplace=True)
                df[["Symbol", "Side", "Entry Price", "Exit Price", "Quantity", "Points", "P&L", "Result", "Reason"]].to_excel(writer, sheet_name="Trade Details", index=False)
            else:
                pd.DataFrame(columns=["Symbol", "Side", "Entry Price", "Exit Price", "Quantity", "Points", "P&L", "Result", "Reason"]).to_excel(writer, sheet_name="Trade Details", index=False)

            # Optional: Add more sheets for symbol analysis, config etc.

    else:
        df.to_excel(excel_path, index=False)  # Basic output without formatting

    logger.info(f"Report generated: {excel_path}")
    return excel_path
