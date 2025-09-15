from __future__ import annotations
import requests
import websocket
import json
import threading
from typing import Any, Dict, List, Optional, Callable
import logging
import time
import uuid
from datetime import datetime, timedelta
from queue import Queue
import ssl

logger = logging.getLogger(__name__)

class DhanAPIError(Exception):
    pass

class DhanAPI:
    BASE_URL = "https://api.dhan.co/v2"
    WEBSOCKET_ORDER_URL = "wss://api-order-update.dhan.co"
    WEBSOCKET_FEED_URL = "wss://api-feed.dhan.co"
    
    def __init__(self, access_token: str, client_id: Optional[str] = None) -> None:
        if not access_token:
            raise ValueError("DhanAPI requires a valid access_token")
        
        self.access_token = access_token
        self.client_id = client_id or "1106596952"
        self.headers = {
            "access-token": self.access_token,
            "Content-Type": "application/json",
        }
        
        if self.client_id:
            self.headers["client-id"] = self.client_id    
        
        self.last_request_time = 0
        self.min_request_interval = 2.0  
        self.rate_limit_backoff = 2.0    
        
        self.ws_feed = None
        self.ws_order = None
        self.ws_feed_thread = None
        self.ws_order_thread = None
        self.is_feed_connected = False
        self.is_order_connected = False
        self.connection_attempts = 0
        self.max_connection_attempts = 3
        
       
        self.live_prices = {}  
        self.live_orders = {}  
        self.price_callbacks = {}  
        self.order_callbacks = []  
        
        self.message_queue = Queue()
        self.processor_thread = None
        self.stop_processing = False
        
       
        self.ltp_cache = {}
        self.cache_duration = 10  

    def _rate_limit_protection(self):
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.BASE_URL}{endpoint}"
        
        for attempt in range(3):
            try:
                self._rate_limit_protection()
                resp = requests.get(url, headers=self.headers, params=params, timeout=30)
                data = resp.json()
                
                if resp.status_code == 429:
                    backoff_time = self.rate_limit_backoff * (2 ** attempt)
                    logger.debug(f"Rate limited on GET {endpoint}, backing off {backoff_time}s")
                    time.sleep(backoff_time)
                    continue
                
                if resp.ok and ("errorCode" not in data or data.get("errorCode") is None):
                    return data
                    
                raise DhanAPIError(f"GET {endpoint} failed: {resp.status_code} {data}")
                
            except (requests.exceptions.Timeout, requests.exceptions.ReadTimeout):
                logger.debug(f"Timeout on GET {endpoint}, attempt {attempt+1}/3...")
                time.sleep(2 * (attempt + 1))
                
        raise DhanAPIError(f"GET {endpoint} failed after retries: Timeout")

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Any:
        url = f"{self.BASE_URL}{endpoint}"
        
        for attempt in range(3):
            try:
                self._rate_limit_protection()
                resp = requests.post(url, headers=self.headers, json=payload, timeout=30)
                data = resp.json()
                
                if resp.status_code == 429:
                    backoff_time = self.rate_limit_backoff * (2 ** attempt)
                    logger.debug(f"Rate limited on POST {endpoint}, backing off {backoff_time}s")
                    time.sleep(backoff_time)
                    continue
                
                if resp.ok and ("errorCode" not in data or data.get("errorCode") is None):
                    return data
                    
                raise DhanAPIError(f"POST {endpoint} failed: {resp.status_code} {data}")
                
            except (requests.exceptions.Timeout, requests.exceptions.ReadTimeout):
                logger.debug(f"Timeout on POST {endpoint}, attempt {attempt+1}/3...")
                time.sleep(2 * (attempt + 1))
                
        raise DhanAPIError(f"POST {endpoint} failed after retries: Timeout")

    # ===== WebSocket Live Market Feed =====
    
    def _on_feed_message(self, ws, message):
        try:
            data = json.loads(message)
            self.message_queue.put(('feed', data))
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to decode feed message: {e}")
    
    def _on_feed_error(self, ws, error):
        logger.debug(f"WebSocket feed error: {error}")
        self.is_feed_connected = False
    
    def _on_feed_close(self, ws, close_status_code, close_msg):
        logger.debug("WebSocket feed connection closed")
        self.is_feed_connected = False
        
    
    
    def _on_feed_open(self, ws):
        logger.info("WebSocket feed connection established")
        self.is_feed_connected = True
        self.connection_attempts = 0
    
    def connect_live_feed(self) -> bool:
        if self.connection_attempts >= self.max_connection_attempts:
            logger.debug("Max WebSocket connection attempts reached, using REST API fallback")
            return False
            
        try:
            self.connection_attempts += 1
            ws_url = f"{self.WEBSOCKET_FEED_URL}?version=2&token={self.access_token}&clientId={self.client_id}&authType=2"
            
            logger.debug(f"Attempting WebSocket connection (attempt {self.connection_attempts}/{self.max_connection_attempts})")
            
            self.ws_feed = websocket.WebSocketApp(
                ws_url,
                on_message=self._on_feed_message,
                on_error=self._on_feed_error,
                on_close=self._on_feed_close,
                on_open=self._on_feed_open
            )
            
            # Start WebSocket in separate thread
            self.ws_feed_thread = threading.Thread(
                target=self.ws_feed.run_forever,
                kwargs={'sslopt': {"cert_reqs": ssl.CERT_NONE}}
            )
            self.ws_feed_thread.daemon = True
            self.ws_feed_thread.start()
            
            # Wait for connection establishment
            max_wait = 5  # Reduced wait time
            waited = 0
            while not self.is_feed_connected and waited < max_wait:
                time.sleep(0.5)
                waited += 0.5
            
            if self.is_feed_connected:
                logger.info("WebSocket feed connected successfully")
                
                # Start message processor if not already running
                if not self.processor_thread or not self.processor_thread.is_alive():
                    self._start_message_processor()
                    
                return True
            else:
                logger.debug("WebSocket connection timeout, will use REST API fallback")
                return False
                
        except Exception as e:
            logger.debug(f"WebSocket connection failed: {e}")
            return False
    
    def _start_message_processor(self):
        """Start background thread to process WebSocket messages"""
        self.stop_processing = False
        self.processor_thread = threading.Thread(target=self._process_messages)
        self.processor_thread.daemon = True
        self.processor_thread.start()
        logger.debug("WebSocket message processor started")
    
    def _process_messages(self):
        while not self.stop_processing:
            try:
                message_type, data = self.message_queue.get(timeout=1.0)
                
                if message_type == 'feed':
                    self._process_feed_message(data)
                elif message_type == 'order':
                    self._process_order_message(data)
                    
                self.message_queue.task_done()
                
            except:
                continue
    
    def _process_feed_message(self, data):
        try:
            if isinstance(data, dict):
                if 'securityId' in data and 'ltp' in data:
                    security_id = str(data['securityId'])
                    ltp = float(data['ltp'])
                    
                    self.live_prices[security_id] = {
                        'ltp': ltp,
                        'timestamp': time.time(),
                        'high': data.get('high'),
                        'low': data.get('low'),
                        'volume': data.get('volume')
                    }
                    
                    if security_id in self.price_callbacks:
                        for callback in self.price_callbacks[security_id]:
                            try:
                                callback(security_id, ltp, data)
                            except Exception as e:
                                logger.debug(f"Callback error: {e}")
                
                elif 'instruments' in data:
                    for instrument in data['instruments']:
                        if 'securityId' in instrument and 'ltp' in instrument:
                            security_id = str(instrument['securityId'])
                            ltp = float(instrument['ltp'])
                            
                            self.live_prices[security_id] = {
                                'ltp': ltp,
                                'timestamp': time.time(),
                                'high': instrument.get('high'),
                                'low': instrument.get('low'),
                                'volume': instrument.get('volume')
                            }
                            
        except Exception as e:
            logger.debug(f"Failed to process feed message: {e}")
    
    def _process_order_message(self, data):
        try:
            if isinstance(data, dict) and 'orderId' in data:
                order_id = str(data['orderId'])
                self.live_orders[order_id] = data
                
                for callback in self.order_callbacks:
                    try:
                        callback(order_id, data)
                    except Exception as e:
                        logger.debug(f"Order callback error: {e}")
                        
        except Exception as e:
            logger.debug(f"Failed to process order message: {e}")
    
    def subscribe_to_price_updates(self, security_id: str, callback: Optional[Callable] = None) -> bool:
        try:
            security_id = str(security_id)
            
            if not self.is_feed_connected:
                if not self.connect_live_feed():
                    logger.debug(f"WebSocket not available, will use REST API for {security_id}")
                    return False
            
   
            if callback:
                if security_id not in self.price_callbacks:
                    self.price_callbacks[security_id] = []
                self.price_callbacks[security_id].append(callback)
            
            subscription_message = {
                "RequestCode": 11,
                "InstrumentCount": 1,
                "InstrumentList": [
                    {
                        "ExchangeSegment": 1,  # NSE
                        "SecurityId": int(security_id)
                    }
                ]
            }
            
            if self.ws_feed and self.is_feed_connected:
                self.ws_feed.send(json.dumps(subscription_message))
                logger.debug(f"Subscribed to live prices for security {security_id}")
                return True
            else:
                logger.debug("WebSocket feed not connected")
                return False
                
        except Exception as e:
            logger.debug(f"Failed to subscribe to price updates for {security_id}: {e}")
            return False
    
    def get_live_ltp(self, security_id: str) -> Optional[float]:
        """Get live LTP from WebSocket feed (preferred method)"""
        security_id = str(security_id)
        
        if security_id in self.live_prices:
            price_data = self.live_prices[security_id]
            
            if time.time() - price_data['timestamp'] < 30:
                return price_data['ltp']
        
        return None

    
    def get_ltp(self, security_id: str, exchange_segment: str = "NSE_EQ", prefer_live: bool = True) -> Optional[float]:
        security_id = str(security_id)
        if prefer_live and self.is_feed_connected:
            live_ltp = self.get_live_ltp(security_id)
            if live_ltp is not None:
                logger.debug(f"LTP for {security_id}: {live_ltp} (WebSocket)")
                return live_ltp
        current_time = time.time()
        cache_key = security_id
        
        if (cache_key in self.ltp_cache and 
            current_time - self.ltp_cache[cache_key]['timestamp'] < self.cache_duration):
            cached_ltp = self.ltp_cache[cache_key]['value']
            if cached_ltp is not None:
                logger.debug(f"LTP for {security_id}: {cached_ltp} (cached)")
                return cached_ltp
        
        try:
            endpoint = "/marketfeed/quote"
            payload = {
                "securityId": security_id,
                "exchangeSegment": exchange_segment,
            }
            
            response = self._post(endpoint, payload)
            
            if response and isinstance(response, dict):
                ltp_sources = [
                    response,
                    response.get("data", {}),
                    response.get("quote", {}),
                    response.get("marketData", {})
                ]
                
                ltp_fields = ["ltp", "lastPrice", "price", "close", "lastTradePrice", "last"]
                
                for source in ltp_sources:
                    if isinstance(source, dict):
                        for field in ltp_fields:
                            if field in source and source[field] is not None:
                                try:
                                    ltp_value = float(source[field])
                                    if ltp_value > 0:
                                        # Cache the result
                                        self.ltp_cache[cache_key] = {
                                            'value': ltp_value,
                                            'timestamp': current_time
                                        }
                                        logger.debug(f"LTP for {security_id}: {ltp_value} (REST API)")
                                        return ltp_value
                                except (ValueError, TypeError):
                                    continue
                                    
        except DhanAPIError as e:
            if "429" in str(e):
                logger.debug(f"Rate limited on LTP for {security_id}")
                self.ltp_cache[cache_key] = {
                    'value': None,
                    'timestamp': current_time
                }
            else:
                logger.debug(f"Market quote failed for {security_id}: {e}")
        
        fallback_ltp = self._get_ltp_from_candles(security_id, exchange_segment)
        if fallback_ltp:
            self.ltp_cache[cache_key] = {
                'value': fallback_ltp,
                'timestamp': current_time
            }
            logger.debug(f"LTP for {security_id}: {fallback_ltp} (candle data)")
            return fallback_ltp
        
        self.ltp_cache[cache_key] = {
            'value': None,
            'timestamp': current_time
        }
        
        logger.debug(f"No LTP available for {security_id} from any source")
        return None

    def _get_ltp_from_candles(self, security_id: str, exchange_segment: str = "NSE_EQ") -> Optional[float]:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            
            raw = self.get_intraday_candles(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument="EQUITY",
                from_date=today,
                to_date=today,
                interval="1m",
            )
            
            if isinstance(raw, dict) and "close" in raw and raw["close"]:
                closes = raw["close"]
                if closes and len(closes) > 0:
                    latest_close = float(closes[-1])
                    if latest_close > 0:
                        return latest_close
                        
        except Exception as e:
            logger.debug(f"Failed to get LTP from candles for {security_id}: {e}")
            
        return None

    # ===== REST API Methods =====
    
    def get_historical_candles(
        self,
        security_id: str,
        exchange_segment: str = "NSE_EQ",
        instrument: str = "EQUITY",
        from_date: str = "",
        to_date: str = "",
        interval: str = "1d",
    ) -> Any:
        endpoint = "/charts/historical"
        payload: Dict[str, Any] = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "fromDate": from_date,
            "toDate": to_date,
            "interval": interval,
        }
        
        logger.debug(f"Fetching historical candles for {security_id}")
        return self._post(endpoint, payload)

    def get_intraday_candles(
        self,
        security_id: str,
        exchange_segment: str = "NSE_EQ",
        instrument: str = "EQUITY",
        from_date: str = "",
        to_date: str = "",
        interval: str = "1m",
    ) -> Any:
        endpoint = "/charts/intraday"
        payload: Dict[str, Any] = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "fromDate": from_date,
            "toDate": to_date,
            "interval": interval,
        }
        
        logger.debug(f"Fetching intraday candles for {security_id}")
        return self._post(endpoint, payload)

    def place_order(
        self,
        security_id: str,
        exchange_segment: str,
        instrument: str,
        transaction_type: str,
        product_type: str,
        order_type: str,
        quantity: int,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
    ) -> Dict[str, Any]:
        endpoint = "/orders"
        
        correlation_id = str(uuid.uuid4())[:12]
        
        payload: Dict[str, Any] = {
            "dhanClientId": self.client_id,
            "correlationId": correlation_id,
            "transactionType": transaction_type,
            "exchangeSegment": exchange_segment,
            "productType": "INTRADAY",
            "orderType": order_type,
            "validity": "DAY",
            "securityId": str(security_id),
            "quantity": quantity,
            "disclosedQuantity": 0,
            "price": 0,
            "triggerPrice": 0,
            "afterMarketOrder": False
        }
        
        logger.info(f"Placing order for {security_id}: {transaction_type} {quantity}")
        return self._post(endpoint, payload)

    def exit_order(self, order_id: str) -> Dict[str, Any]:
        endpoint = f"/orders/{order_id}/exit"
        logger.debug(f"Exiting order: {order_id}")
        return self._post(endpoint, {})

    def get_positions(self) -> List[Dict[str, Any]]:
        try:
            return self._get("/positions")
        except Exception as e:
            logger.debug(f"Failed to get positions: {e}")
            return []

    def get_orders(self) -> List[Dict[str, Any]]:
        try:
            return self._get("/orders")
        except Exception as e:
            logger.debug(f"Failed to get orders: {e}")
            return []

    # ===== Cleanup Methods =====
    
    def disconnect_websockets(self):
        self.stop_processing = True
        
        if self.ws_feed:
            try:
                self.ws_feed.close()
            except:
                pass
            self.is_feed_connected = False
        
        if self.ws_order:
            try:
                self.ws_order.close()
            except:
                pass
            self.is_order_connected = False
        self.live_prices.clear()
        self.price_callbacks.clear()
        
        logger.debug("WebSocket connections closed")
    
    def __del__(self):
        try:
            self.disconnect_websockets()
        except:
            pass   
    def get_connection_status(self) -> Dict[str, bool]:
        return {
            "feed_connected": self.is_feed_connected,
            "order_connected": self.is_order_connected,
            "live_prices_count": len(self.live_prices)
        }
    
    def get_subscribed_securities(self) -> List[str]:
        return list(self.live_prices.keys())

    def clear_cache(self):
        self.ltp_cache.clear()
        logger.debug("LTP cache cleared")
