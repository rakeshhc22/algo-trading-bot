from dhanhq import dhanhq
import pandas as pd

# Your credentials
client_id = "1106596952"
access_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzU4NDI4MzIyLCJ0b2tlbkNvbnN1bWVyVHlwZSI6IlNFTEYiLCJ3ZWJob29rVXJsIjoiIiwiZGhhbkNsaWVudElkIjoiMTEwNjU5Njk1MiJ9.ySXuz-hWmGtqQr8opIEHPvI-AEGD6gfxlrH8SgqXysV6zMJYssFh4xjU5vQe3Rfocms6qKocTJtqToiI0qfYIw"


dhan = dhanhq(client_id, access_token)

# Fetch full security list
df = dhan.fetch_security_list("compact")

# Filter for Cash Market (Equity segment only)
cash_market_df = df[df["SEM_SERIES"] == "EQ"]

# Symbols you want to look up
symbols_to_find = ["SBIN", "LTF"]

# Normalize case for matching
cash_market_df['SM_SYMBOL_NAME'] = cash_market_df['SM_SYMBOL_NAME'].str.upper()
symbols_to_find = [s.upper() for s in symbols_to_find]

# Filter by symbol names
result = cash_market_df[cash_market_df['SM_SYMBOL_NAME'].isin(symbols_to_find)][
    ['SM_SYMBOL_NAME', 'SEM_SMST_SECURITY_ID', 'SEM_EXM_EXCH_ID']
]

print(result)

