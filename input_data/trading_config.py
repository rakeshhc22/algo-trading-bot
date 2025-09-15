from __future__ import annotations

import pandas as pd
from pathlib import Path
from typing import List, Dict, Any
from datetime import time
import logging

logger = logging.getLogger(__name__)

class TradingInputData:
    """Load and validate trading parameters from input file - accepts any values without BRD restrictions"""

    def __init__(self, input_file_path: str = "input_data/trading_parameters.csv"):
        self.input_file_path = Path(input_file_path)
        self.trading_params = self._load_input_file()

    def _load_input_file(self) -> pd.DataFrame:
        """Load input data file without any restrictions"""
        try:
            if not self.input_file_path.exists():
                raise FileNotFoundError(f"Input file not found: {self.input_file_path}")

            # Load CSV file
            df = pd.read_csv(self.input_file_path)

            # Validate only required columns exist
            required_columns = [
                'SL_NO', 'SCRIPT_LIST', 'STOP_LOSS_PERCENT',
                'NO_OF_SHARES', 'ENTRY_TIME', 'EXIT_TIME'
            ]

            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns: {missing_columns}")

            # Basic data type validation only
            self._validate_data_types(df)

            logger.info(f"Loaded {len(df)} trading parameters from {self.input_file_path}")
            return df

        except Exception as e:
            logger.error(f"Failed to load input file: {e}")
            raise

    def _validate_data_types(self, df: pd.DataFrame):
        """Basic data type validation only - no value restrictions"""
        try:
            # Ensure numeric columns are numeric
            df['STOP_LOSS_PERCENT'] = pd.to_numeric(df['STOP_LOSS_PERCENT'], errors='coerce')
            df['NO_OF_SHARES'] = pd.to_numeric(df['NO_OF_SHARES'], errors='coerce')
            
            # Check for any conversion errors
            if df['STOP_LOSS_PERCENT'].isna().any():
                raise ValueError("Invalid values in STOP_LOSS_PERCENT column")
            if df['NO_OF_SHARES'].isna().any():
                raise ValueError("Invalid values in NO_OF_SHARES column")

            logger.info("Data type validation completed")

        except Exception as e:
            logger.error(f"Data type validation failed: {e}")
            raise

    def get_symbols(self) -> List[str]:
        """Get list of symbols to trade"""
        return self.trading_params['SCRIPT_LIST'].tolist()

    def get_stop_loss_percent(self, symbol: str = None) -> float:
        """Get stop-loss percentage for symbol (or first row if no symbol specified)"""
        if symbol:
            symbol_row = self.trading_params[self.trading_params['SCRIPT_LIST'] == symbol]
            if symbol_row.empty:
                raise ValueError(f"Symbol {symbol} not found in input data")
            return symbol_row['STOP_LOSS_PERCENT'].iloc[0] / 100
        return self.trading_params['STOP_LOSS_PERCENT'].iloc[0] / 100

    def get_quantity_per_trade(self, symbol: str = None) -> int:
        """Get quantity per trade for symbol (or first row if no symbol specified)"""
        if symbol:
            symbol_row = self.trading_params[self.trading_params['SCRIPT_LIST'] == symbol]
            if symbol_row.empty:
                raise ValueError(f"Symbol {symbol} not found in input data")
            return int(symbol_row['NO_OF_SHARES'].iloc[0])
        return int(self.trading_params['NO_OF_SHARES'].iloc[0])

    def get_entry_time(self, symbol: str = None) -> time:
        """Get entry time for symbol (or first row if no symbol specified)"""
        if symbol:
            symbol_row = self.trading_params[self.trading_params['SCRIPT_LIST'] == symbol]
            if symbol_row.empty:
                raise ValueError(f"Symbol {symbol} not found in input data")
            time_str = symbol_row['ENTRY_TIME'].iloc[0]
        else:
            time_str = self.trading_params['ENTRY_TIME'].iloc[0]
        
        h, m, s = map(int, time_str.split(':'))
        return time(h, m, s)

    def get_exit_time(self, symbol: str = None) -> time:
        """Get exit time for symbol (or first row if no symbol specified)"""
        if symbol:
            symbol_row = self.trading_params[self.trading_params['SCRIPT_LIST'] == symbol]
            if symbol_row.empty:
                raise ValueError(f"Symbol {symbol} not found in input data")
            time_str = symbol_row['EXIT_TIME'].iloc[0]
        else:
            time_str = self.trading_params['EXIT_TIME'].iloc[0]
        
        h, m, s = map(int, time_str.split(':'))
        return time(h, m, s)

    def get_symbol_config(self, symbol: str) -> Dict[str, Any]:
        """Get complete configuration for specific symbol"""
        symbol_row = self.trading_params[self.trading_params['SCRIPT_LIST'] == symbol]
        
        if symbol_row.empty:
            raise ValueError(f"Symbol {symbol} not found in input data")

        row = symbol_row.iloc[0]
        return {
            'sl_no': row['SL_NO'],
            'symbol': row['SCRIPT_LIST'],
            'stop_loss_percent': row['STOP_LOSS_PERCENT'] / 100,
            'quantity': int(row['NO_OF_SHARES']),
            'entry_time': row['ENTRY_TIME'],
            'exit_time': row['EXIT_TIME']
        }

    def get_all_symbol_configs(self) -> List[Dict[str, Any]]:
        """Get configuration for all symbols"""
        configs = []
        for _, row in self.trading_params.iterrows():
            configs.append({
                'sl_no': row['SL_NO'],
                'symbol': row['SCRIPT_LIST'],
                'stop_loss_percent': row['STOP_LOSS_PERCENT'] / 100,
                'quantity': int(row['NO_OF_SHARES']),
                'entry_time': row['ENTRY_TIME'],
                'exit_time': row['EXIT_TIME']
            })
        return configs

    def display_config(self):
        """Display loaded configuration for verification"""
        print("\n" + "═" * 70)
        print("📋 TRADING CONFIGURATION (From CSV Input File)")
        print("═" * 70)
        print(f"📁 Input File: {self.input_file_path}")
        print(f"📊 Total Symbols: {len(self.get_symbols())}")
        print(f"🎯 Symbols: {', '.join(self.get_symbols())}")
        print("═" * 70)

        # Display symbol-wise details
        print("\n📋 SYMBOL-WISE CONFIGURATION:")
        print("-" * 70)
        print(f"{'SL#':<4} {'SYMBOL':<12} {'STOP_LOSS%':<10} {'QTY':<5} {'ENTRY':<10} {'EXIT':<10}")
        print("-" * 70)
        
        for _, row in self.trading_params.iterrows():
            print(f"{row['SL_NO']:<4} {row['SCRIPT_LIST']:<12} "
                  f"{row['STOP_LOSS_PERCENT']:<10.2f} {row['NO_OF_SHARES']:<5} "
                  f"{row['ENTRY_TIME']:<10} {row['EXIT_TIME']:<10}")
        print("-" * 70)

    def update_symbol_config(self, symbol: str, **kwargs):
        """Update configuration for a specific symbol"""
        symbol_idx = self.trading_params[self.trading_params['SCRIPT_LIST'] == symbol].index
        
        if len(symbol_idx) == 0:
            raise ValueError(f"Symbol {symbol} not found in configuration")
        
        idx = symbol_idx[0]
        
        # Update allowed fields
        allowed_fields = ['STOP_LOSS_PERCENT', 'NO_OF_SHARES', 'ENTRY_TIME', 'EXIT_TIME']
        for field, value in kwargs.items():
            if field in allowed_fields:
                self.trading_params.at[idx, field] = value
                logger.info(f"Updated {symbol} {field} to {value}")
            else:
                logger.warning(f"Field {field} is not allowed to be updated")

    def save_config(self, output_path: str = None):
        """Save current configuration back to CSV"""
        if output_path is None:
            output_path = self.input_file_path
        
        self.trading_params.to_csv(output_path, index=False)
        logger.info(f"Configuration saved to {output_path}")

# Convenience function for easy integration
def load_trading_config(input_file: str = "input_data/trading_parameters.csv") -> TradingInputData:
    """Load trading configuration from input file without any restrictions"""
    return TradingInputData(input_file)