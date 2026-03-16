"""
Utility functions for the trading bot.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """
    Get current UTC time as timezone-aware datetime.
    
    This replaces the deprecated datetime.utcnow() which will be removed
    in Python 3.12+.
    """
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Get current UTC time as ISO format string."""
    return utc_now().isoformat()
