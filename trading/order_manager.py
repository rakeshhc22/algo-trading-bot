from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import logging

from data.dhan_api import DhanAPI, DhanAPIError
from strategy.z3_strategy import TradePlan
from strategy.signal_generator import SignalSide

logger = logging.getLogger(__name__)

@dataclass
class OrderFill:
    order_id: str
    symbol: str
    side: SignalSide
    entry_price: float
    quantity: int

class OrderManager:
    def __init__(self, api: DhanAPI, symbol_map: Dict[str, str], exchange: str = "NSE_EQ") -> None:
        self.api = api
        self.symbol_map = {k.upper(): str(v) for k, v in symbol_map.items()}
        self.exchange = exchange

    def _transaction_type(self, side: SignalSide) -> str:
        return "BUY" if side == SignalSide.LONG else "SELL"

    def _reverse_transaction_type(self, side: SignalSide) -> str:
        return "SELL" if side == SignalSide.LONG else "BUY"

    def get_ltp(self, symbol: str) -> Optional[float]:
        try:
            sym = symbol.upper()
            if sym not in self.symbol_map:
                logger.error(f"Symbol {sym} not found in symbol_map")
                return None
            security_id = self.symbol_map[sym]
            ltp = self.api.get_ltp(security_id, self.exchange)
            if ltp is not None:
                logger.debug(f"LTP for {symbol}: {ltp}")
                return ltp
            else:
                logger.warning(f"No LTP available for {symbol}")
                return None
        except Exception as e:
            logger.error(f"Failed to get LTP for {symbol}: {e}")
            return None

    def get_multiple_ltps_optimized(self, symbols: List[str]) -> Dict[str, Optional[float]]:
        results = {}
        for symbol in symbols:
            results[symbol] = self.get_ltp(symbol)
        return results

    def place_entry_order(self, plan: TradePlan) -> OrderFill:
        try:
            sym = plan.symbol.upper()
            if sym not in self.symbol_map:
                raise DhanAPIError(f"Symbol {sym} not found in symbol_map")
            
            security_id = self.symbol_map[sym]
            logger.info(f"Placing {plan.side.name} order for {plan.symbol} (securityId: {security_id})")
            
            # Ensure quantity is an integer, not string
            quantity_int = int(plan.quantity)
            
            # Prepare order parameters with proper data types
            order_params = {
                "security_id": security_id,
                "exchange_segment": self.exchange,
                "instrument": "EQUITY",
                "transaction_type": self._transaction_type(plan.side),
                "product_type": plan.product_type,
                "order_type": plan.order_type,
                "quantity": quantity_int,  # Ensure it's integer
            }
            
            logger.debug(f"Order parameters: {order_params}")
            
            payload = self.api.place_order(**order_params)
            
            # Extract order ID from various possible response formats
            order_id = str(
                payload.get("order_id")
                or payload.get("orderId")
                or payload.get("id")
                or payload.get("orderNumber")
                or payload.get("data", {}).get("order_id", "")
                or payload.get("data", {}).get("orderId", "")
                or ""
            )
            
            if not order_id or order_id == "":
                logger.error(f"Order response for {plan.symbol}: {payload}")
                raise DhanAPIError("Could not determine order_id from response")
            
            logger.info(f"Order placed successfully for {plan.symbol}: order_id={order_id}")
            
            return OrderFill(
                order_id=order_id,
                symbol=plan.symbol,
                side=plan.side,
                entry_price=plan.entry_price,
                quantity=quantity_int,
            )
            
        except Exception as e:
            logger.error(f"Failed to place order for {plan.symbol}: {e}")
            logger.exception("Detailed order placement error:")
            raise

    def exit_position(self, fill: OrderFill) -> Dict[str, Any]:
        logger.info(f"Exiting position for {fill.symbol} (order_id: {fill.order_id})")
        
        try:
            # Try native exit first if available
            if hasattr(self.api, 'exit_order'):
                try:
                    resp = self.api.exit_order(fill.order_id)
                    logger.info(f"Position exited using native exit_order for {fill.symbol}")
                    return {"method": "exit_order", "response": resp}
                except Exception as e:
                    logger.warning(f"Native exit_order failed for {fill.symbol}: {e}")
            
            # Fallback to reverse order
            security_id = self.symbol_map.get(fill.symbol.upper())
            if not security_id:
                raise DhanAPIError(f"Symbol {fill.symbol} not found for exit")
            
            # Ensure quantity is an integer
            exit_quantity = int(fill.quantity)
            
            exit_params = {
                "security_id": security_id,
                "exchange_segment": self.exchange,
                "instrument": "EQUITY",
                "transaction_type": self._reverse_transaction_type(fill.side),
                "product_type": "MIS",  # Intraday MIS for exit
                "order_type": "MARKET",
                "quantity": exit_quantity,
            }
            
            logger.debug(f"Exit order parameters: {exit_params}")
            
            resp = self.api.place_order(**exit_params)
            
            logger.info(f"Position exited via reverse MARKET order for {fill.symbol}")
            return {"method": "reverse_order", "response": resp}
            
        except Exception as e:
            logger.error(f"Failed to exit position for {fill.symbol}: {e}")
            logger.exception("Detailed exit error:")
            raise
    
    def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of an order
        
        Args:
            order_id: ID of the order
            
        Returns:
            Order status information or None if failed
        """
        try:
            if hasattr(self.api, 'get_order_by_id'):
                response = self.api.get_order_by_id(order_id)
            elif hasattr(self.api, 'get_order_status'):
                response = self.api.get_order_status(order_id)
            else:
                logger.warning("No order status method available in API")
                return None
            
            if response and isinstance(response, dict):
                if 'data' in response:
                    return response['data']
                else:
                    return response
            else:
                logger.error(f"Invalid response format for order status {order_id}: {response}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting order status for {order_id}: {str(e)}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a pending order
        
        Args:
            order_id: ID of the order to cancel
            
        Returns:
            True if cancellation successful, False otherwise
        """
        try:
            if hasattr(self.api, 'cancel_order'):
                response = self.api.cancel_order(order_id)
                
                if response and (
                    response.get('status') == 'success' or 
                    response.get('orderStatus') == 'CANCELLED' or
                    'data' in response
                ):
                    logger.info(f"Order {order_id} cancelled successfully")
                    return True
                else:
                    logger.error(f"Order cancellation failed for {order_id}: {response}")
                    return False
            else:
                logger.warning("Cancel order method not available in API")
                return False
                
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {str(e)}")
            return False
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get current positions
        
        Returns:
            List of positions or empty list if failed
        """
        try:
            if hasattr(self.api, 'get_positions'):
                response = self.api.get_positions()
                if response and 'data' in response:
                    return response['data']
                elif response and isinstance(response, list):
                    return response
                else:
                    logger.warning(f"Unexpected positions response format: {response}")
                    return []
            else:
                logger.warning("Get positions method not available in API")
                return []
                
        except Exception as e:
            logger.error(f"Error getting positions: {str(e)}")
            return []
    
    def validate_symbol_mapping(self, symbols: List[str]) -> Dict[str, bool]:
        """
        Validate that all symbols have corresponding security IDs
        
        Args:
            symbols: List of symbols to validate
            
        Returns:
            Dictionary mapping symbols to validation status
        """
        validation_results = {}
        
        for symbol in symbols:
            sym_upper = symbol.upper()
            if sym_upper in self.symbol_map:
                security_id = self.symbol_map[sym_upper]
                if security_id and str(security_id).strip():
                    validation_results[symbol] = True
                    logger.debug(f"Symbol {symbol} -> Security ID {security_id}: Valid")
                else:
                    validation_results[symbol] = False
                    logger.error(f"Symbol {symbol} has empty security ID")
            else:
                validation_results[symbol] = False
                logger.error(f"Symbol {symbol} not found in symbol mapping")
        
        return validation_results
    
    def get_symbol_info(self, symbol: str) -> Optional[str]:
        """
        Get security ID for a symbol
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Security ID or None if not found
        """
        sym_upper = symbol.upper()
        return self.symbol_map.get(sym_upper)