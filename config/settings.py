from __future__ import annotations

from pathlib import Path
import os

def get_reports_directory() -> Path:
    """Get reports directory - only system setting still needed"""
    return Path(os.getenv("Z3_REPORTS_DIR", "reports")).expanduser().resolve()

def get_logs_directory() -> Path:
    """Get logs directory - only system setting still needed"""  
    return Path(os.getenv("Z3_LOGS_DIR", "logs")).expanduser().resolve()


