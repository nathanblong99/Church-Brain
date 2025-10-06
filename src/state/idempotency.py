from __future__ import annotations
from .repository import GLOBAL_DB


def check_and_record(key: str, data: dict | None = None) -> bool:
    if GLOBAL_DB.has_idempotency_key(key):
        return False
    # For Phase 1 we piggyback on outbox recording or explicit records
    # Minimal behavior: store an empty marker
    GLOBAL_DB.idempotency[key] = data or {}
    return True
