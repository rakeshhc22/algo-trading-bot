from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Set

import pandas as pd
from zoneinfo import ZoneInfo

from data.dhan_api import DhanAPI, DhanAPIError

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class Candle:
    symbol: str
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

class MarketDataFetcher:
    """
    Fetches historical and intraday candle data via the Dhan API,
    with properly formatted requests to avoid DH-905 errors.
    """

    def __init__(
        self,
        api: DhanAPI,
        symbol_map: Dict[str, int],
        exchange: str = "NSE_EQ",
        instrument: str = "EQUITY",
        holidays: Optional[Set[str]] = None,
    ) -> None:
        self.api = api
        # Map symbol strings (upper case) to integer security IDs
        self.symbol_map = {k.upper(): int(v) for k, v in symbol_map.items()}
        self.exchange = exchange
        self.instrument = instrument
        self.tz = ZoneInfo("Asia/Kolkata")
        self.holidays = set(holidays or [])

    def _is_trading_day(self, d: datetime) -> bool:
        # Saturday and Sunday are not trading days
        if d.weekday() >= 5:
            return False
        # Exclude known holidays
        return d.strftime("%Y-%m-%d") not in self.holidays

    def _previous_trading_day(self, ref: datetime) -> Optional[datetime]:
        d = ref - timedelta(days=1)
        for _ in range(7):
            if self._is_trading_day(d):
                return d
            d -= timedelta(days=1)
        return None

    def get_yesterdays_close_1529(self, symbol: str, today: datetime) -> Optional[float]:
        """
        Get the previous day's closing price. Since intraday historical data is typically
        not available via APIs, we use the daily closing price as a proxy.
        """
        sym = symbol.upper()
        if sym not in self.symbol_map:
            logger.error(f"Symbol {sym} not found in symbol_map.")
            return None

        security_id = self.symbol_map[sym]
        prev_day = self._previous_trading_day(today)
        if not prev_day:
            logger.error(f"No previous trading day found before {today.date()}.")
            return None

        # Skip intraday attempt since it typically fails for historical data
        # Go directly to daily historical data which is more reliable
        try:
            # Get last 5 trading days to ensure we get the data
            start = prev_day - timedelta(days=10)
            raw = self._fetch_historical(security_id, start, prev_day)
            candles = self._normalize_candles(sym, raw)
            
            if candles:
                # Find the candle for the previous trading day
                for c in reversed(candles):
                    if c.date.date() == prev_day.date():
                        logger.info(f"Found {sym} previous day close: {c.close} on {c.date.date()}")
                        return c.close
                
                # If exact date not found, use the most recent available
                if candles:
                    latest = candles[-1]
                    logger.info(f"Using latest available close for {sym}: {latest.close} on {latest.date.date()}")
                    return latest.close

        except DhanAPIError as e:
            logger.error(f"Historical data failed for {sym}: {e}")

        logger.warning(f"No previous day data available for {sym}")
        return None

    def get_todays_entry_price_0924(self, symbol: str, today: datetime) -> Optional[float]:
        """
        Get the closing price at 09:24:59 on the current day.
        If intraday data is unavailable, fall back to LTP.
        """
        sym = symbol.upper()
        if sym not in self.symbol_map:
            logger.error(f"Symbol {sym} not found in symbol_map.")
            return None

        security_id = self.symbol_map[sym]
        try:
            raw = self._fetch_intraday(security_id, today, today)
            candles = self._normalize_candles(sym, raw)
            if candles:
                target = today.replace(hour=9, minute=24, second=59, microsecond=0, tzinfo=self.tz)
                best = min(candles, key=lambda c: abs(c.date - target), default=None)
                if best:
                    logger.debug(f"Found {sym} entry price: {best.close} at {best.date}")
                    return best.close

        except DhanAPIError as e:
            logger.warning(f"Intraday data unavailable for {sym} on {today.date()}: {e}")

        # Fallback to LTP
        try:
            ltp = self.api.get_ltp(str(security_id), exchange_segment=self.exchange)
            if ltp:
                logger.debug(f"Using LTP for {sym} entry price: {ltp}")
                return ltp

        except Exception as e:
            logger.error(f"LTP fallback failed for {sym}: {e}")

        return None

    def get_current_ltp(self, symbol: str) -> Optional[float]:
        sym = symbol.upper()
        sec_id = self.symbol_map.get(sym)
        if not sec_id:
            logger.error(f"Symbol {sym} not found in symbol_map.")
            return None
        return self.api.get_ltp(str(sec_id), exchange_segment=self.exchange)

    def _fetch_intraday(self, security_id: int, day_from: datetime, day_to: datetime) -> Any:
        """
        Fetch intraday data using the exact format that works in Postman
        """
        endpoint = "/charts/intraday"
        
        # Use the EXACT format from working Postman request
        payload = {
            "securityId": int(security_id),  # Ensure it's an integer
            "exchangeSegment": self.exchange,
            "instrument": self.instrument,
            "fromDate": day_from.strftime("%Y-%m-%d"),
            "toDate": day_to.strftime("%Y-%m-%d"),
            "interval": "1m"
        }
        
        logger.debug(f"Intraday Request Payload: {payload}")
        result = self.api._post(endpoint, payload)
        logger.debug(f"Intraday Response Type: {type(result)}")
        return result

    def _fetch_historical(self, security_id: int, start: datetime, end: datetime) -> Any:
        """
        Fetch historical data using the exact format that works in Postman
        """
        endpoint = "/charts/historical"
        
        # Use the EXACT format from working Postman request
        payload = {
            "securityId": int(security_id),  # Ensure it's an integer
            "exchangeSegment": self.exchange,
            "instrument": self.instrument,
            "fromDate": start.strftime("%Y-%m-%d"),
            "toDate": end.strftime("%Y-%m-%d"),
            "interval": "1d"
        }
        
        logger.debug(f"Historical Request Payload: {payload}")
        result = self.api._post(endpoint, payload)
        logger.debug(f"Historical Response Type: {type(result)}")
        return result

    def _normalize_candles(self, symbol: str, raw: Any) -> List[Candle]:
        """
        Convert raw API response data into Candle objects.
        Enhanced to handle various Dhan API response formats.
        """
        candles: List[Candle] = []
        
        if not raw:
            logger.warning(f"Empty or null response for {symbol}")
            return candles

        logger.debug(f"Normalizing candles for {symbol}, raw data type: {type(raw)}")
        
        try:
            # Handle nested data structure
            data = raw
            if isinstance(raw, dict):
                # Check for nested data
                if 'data' in raw:
                    data = raw['data']
                elif 'candles' in raw:
                    data = raw['candles']

            # Format 1: dict-of-lists format (most common for Dhan API)
            if isinstance(data, dict) and any(key in data for key in ['close', 'open', 'high', 'low']):
                opens = data.get("open", [])
                highs = data.get("high", [])
                lows = data.get("low", [])
                closes = data.get("close", [])
                volumes = data.get("volume", [])
                times = data.get("startTime", data.get("time", data.get("timestamp", [])))
                
                if not all([opens, highs, lows, closes, times]):
                    logger.warning(f"Missing required OHLC data for {symbol}")
                    return candles
                
                n = min(len(opens), len(highs), len(lows), len(closes), len(times))
                logger.debug(f"Found {n} candles for {symbol}")

                for i in range(n):
                    try:
                        dt = self._parse_timestamp(times[i])
                        candle = Candle(
                            symbol=symbol,
                            date=dt,
                            open=float(opens[i]),
                            high=float(highs[i]),
                            low=float(lows[i]),
                            close=float(closes[i]),
                            volume=int(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0,
                        )
                        candles.append(candle)
                    except (ValueError, TypeError, IndexError) as e:
                        logger.debug(f"Skipping invalid candle data at index {i}: {e}")
                        continue
                        
                return candles

            # Format 2: list-of-dicts format
            elif isinstance(data, list) and data:
                logger.debug(f"Processing list format with {len(data)} items")
                for i, item in enumerate(data):
                    try:
                        if not isinstance(item, dict):
                            continue
                            
                        ts = item.get("startTime") or item.get("timestamp") or item.get("time")
                        if not ts:
                            logger.debug(f"No timestamp in item {i}")
                            continue
                            
                        dt = self._parse_timestamp(ts)
                        candle = Candle(
                            symbol=symbol,
                            date=dt,
                            open=float(item.get("open", 0)),
                            high=float(item.get("high", 0)),
                            low=float(item.get("low", 0)),
                            close=float(item.get("close", 0)),
                            volume=int(item.get("volume", 0) or 0),
                        )
                        candles.append(candle)
                    except (ValueError, TypeError, KeyError) as e:
                        logger.debug(f"Skipping invalid item at index {i}: {e}")
                        continue
                        
                return candles

            else:
                logger.warning(f"Unexpected candle data format for {symbol}: {type(data)}")
                if isinstance(data, dict):
                    logger.debug(f"Dict keys: {list(data.keys())}")
                return candles

        except Exception as e:
            logger.error(f"Error normalizing candles for {symbol}: {e}")
            return candles

    def _parse_timestamp(self, ts: Any) -> datetime:
        """
        Parse a timestamp string or epoch millis/seconds into an aware IST datetime.
        Enhanced to handle various timestamp formats from Dhan API.
        """
        ist = ZoneInfo("Asia/Kolkata")

        if ts is None:
            return datetime.now(ist)

        # String timestamp
        if isinstance(ts, str):
            try:
                # Try ISO format first
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc).astimezone(ist)
                else:
                    dt = dt.astimezone(ist)
                return dt
            except (ValueError, AttributeError):
                # Try parsing as epoch string
                try:
                    ts_float = float(ts)
                    if ts_float > 1e12:
                        dt = datetime.fromtimestamp(ts_float / 1000, tz=timezone.utc).astimezone(ist)
                    else:
                        dt = datetime.fromtimestamp(ts_float, tz=timezone.utc).astimezone(ist)
                    return dt
                except (ValueError, OverflowError):
                    pass

        # Numeric timestamp
        if isinstance(ts, (int, float)):
            try:
                if ts > 1e12:  # Milliseconds
                    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(ist)
                else:  # Seconds
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ist)
                return dt
            except (OverflowError, ValueError):
                pass

        # Fallback to current time
        logger.warning(f"Could not parse timestamp: {ts}, using current time")
        return datetime.now(ist)