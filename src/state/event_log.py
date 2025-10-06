from __future__ import annotations
from typing import Optional, Dict, Any
from .repository import GLOBAL_DB
from .models import EventLogEntry, new_id
from datetime import datetime


def log(kind: str, correlation_id: str, actor: str, tenant_id: str, shard: Optional[str], data: Dict[str, Any]):
    entry = EventLogEntry(
        id=new_id(),
        timestamp=datetime.utcnow(),
        correlation_id=correlation_id,
        actor=actor,
        tenant_id=tenant_id,
        shard=shard,
        kind=kind,
        data=data
    )
    GLOBAL_DB.append_event(entry)
    return entry
