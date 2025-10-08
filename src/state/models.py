from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import uuid

ISO8601 = str

# Core domain lightweight models (Phase 1 in-memory only)

def _now() -> datetime:
    return datetime.utcnow()

@dataclass
class EventLogEntry:
    id: str
    timestamp: datetime
    correlation_id: str
    actor: str
    tenant_id: str
    shard: Optional[str]
    kind: str  # plan_created, verb_executed, allocation_hold, allocation_confirm, authz_denied, etc.
    data: Dict[str, Any]

@dataclass
class VolunteerRequest:
    id: str
    tenant_id: str
    basketball_needed: int
    volleyball_needed: int
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    # assignments: role -> List[person_id]
    assignments: Dict[str, List[str]] = field(default_factory=lambda: {"basketball": [], "volleyball": []})

@dataclass
class RoomHold:
    id: str
    tenant_id: str
    room_id: str
    start: datetime
    end: datetime
    status: str  # HOLD | CONFIRMED | CANCELED
    expires_at: datetime
    request_id: Optional[str] = None  # link to volunteer/campaign event key if needed

    def is_expired(self) -> bool:
        return self.status == "HOLD" and _now() > self.expires_at

@dataclass
class MessageOutboxItem:
    id: str
    tenant_id: str
    channel: str  # sms | email | notify
    to: str
    template: str
    variables: Dict[str, Any]
    idempotency_key: str
    created_at: datetime = field(default_factory=_now)

@dataclass
class IdempotencyRecord:
    key: str
    created_at: datetime = field(default_factory=_now)
    data: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ShardLock:
    shard: str
    owner: str
    acquired_at: datetime = field(default_factory=_now)
    expires_at: datetime = field(default_factory=lambda: _now() + timedelta(seconds=30))

    def is_expired(self) -> bool:
        return _now() > self.expires_at

# Simple role-based actor
@dataclass
class Actor:
    id: str
    roles: List[str]
    display: Optional[str] = None

# Guest connections (volunteer hosts for new guests)
@dataclass
class GuestConnectionVolunteer:
    id: str
    tenant_id: str
    name: str
    phone: str
    age_range: str
    gender: str
    marital_status: str
    active: bool = True
    last_matched_at: Optional[datetime] = None
    currently_assigned_request_id: Optional[str] = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

@dataclass
class GuestConnectionRequest:
    id: str
    tenant_id: str
    guest_name: str
    contact: str
    age_range: str
    gender: str
    marital_status: str
    status: str = "OPEN"  # OPEN | MATCHED | CLOSED
    volunteer_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def is_open(self) -> bool:
        return self.status == "OPEN"

# Utility factories

def new_id() -> str:
    return uuid.uuid4().hex
