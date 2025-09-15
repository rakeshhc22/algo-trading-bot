from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

@dataclass(frozen=True)
class DhanCredentials:
    access_token: str
    client_id: Optional[str] = None
    environment: str = "live"

    def as_dhan_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.access_token:
            headers["access-token"] = self.access_token
        if self.client_id:
            headers["client-id"] = self.client_id
        return headers

def load_credentials() -> DhanCredentials:
    """Load API credentials - still needed for trading"""
    if load_dotenv is not None:
        load_dotenv()

    access_token = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
    client_id = os.getenv("DHAN_CLIENT_ID")
    environment = (os.getenv("DHAN_ENV") or "live").strip().lower()

    if not access_token:
        raise RuntimeError(
            "Missing DHAN_ACCESS_TOKEN. Please set it in your environment or .env file."
        )

    return DhanCredentials(
        access_token=access_token,
        client_id=client_id.strip() if client_id else None,
        environment=environment,
    )
