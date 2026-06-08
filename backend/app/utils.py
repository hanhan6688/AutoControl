"""Shared utility functions for the Mobile AI TestOps backend."""

from datetime import datetime


def utc_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format with milliseconds."""
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
