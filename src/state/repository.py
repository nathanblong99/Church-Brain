from __future__ import annotations
from typing import Dict, List, Optional, Any, Iterable
from .models import (
    EventLogEntry, VolunteerRequest, RoomHold, MessageOutboxItem,
    IdempotencyRecord, ShardLock, new_id
)
from datetime import datetime, timedelta
import threading

_NOW = datetime.utcnow

class InMemoryDB:
    def __init__(self):
        self.event_log: List[EventLogEntry] = []
        self.volunteer_requests: Dict[str, VolunteerRequest] = {}
        self.room_holds: Dict[str, RoomHold] = {}
        self.outbox: Dict[str, MessageOutboxItem] = {}
        self.idempotency: Dict[str, IdempotencyRecord] = {}
        self.shard_locks: Dict[str, ShardLock] = {}
        # Conversation state (ephemeral) keyed by correlation_id
        self.conversation_state: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    # Event log
    def append_event(self, entry: EventLogEntry):
        with self._lock:
            self.event_log.append(entry)

    # Volunteer requests
    def save_volunteer_request(self, req: VolunteerRequest):
        with self._lock:
            req.updated_at = _NOW()
            self.volunteer_requests[req.id] = req

    def get_volunteer_request(self, req_id: str) -> Optional[VolunteerRequest]:
        return self.volunteer_requests.get(req_id)

    # Room holds
    def save_room_hold(self, hold: RoomHold):
        with self._lock:
            self.room_holds[hold.id] = hold

    def get_active_room_holds(self, tenant_id: str, room_id: str):
        now = _NOW()
        return [h for h in self.room_holds.values() if h.tenant_id == tenant_id and h.room_id == room_id and h.status in ("HOLD","CONFIRMED") and not h.is_expired()]

    # Outbox / idempotency
    def record_outbox_item(self, item: MessageOutboxItem) -> bool:
        with self._lock:
            if item.idempotency_key in self.idempotency:
                return False
            self.idempotency[item.idempotency_key] = IdempotencyRecord(key=item.idempotency_key, data={"outbox_id": item.id})
            self.outbox[item.id] = item
            return True

    def has_idempotency_key(self, key: str) -> bool:
        return key in self.idempotency

    # Shard lock (coarse) - non-blocking acquire
    def acquire_shard(self, shard: str, owner: str, ttl_seconds: int = 30) -> bool:
        with self._lock:
            existing = self.shard_locks.get(shard)
            if existing and not existing.is_expired() and existing.owner != owner:
                return False
            expires = _NOW() + timedelta(seconds=ttl_seconds)
            self.shard_locks[shard] = ShardLock(shard=shard, owner=owner, expires_at=expires)
            return True

    def release_shard(self, shard: str, owner: str):
        with self._lock:
            existing = self.shard_locks.get(shard)
            if existing and existing.owner == owner:
                del self.shard_locks[shard]

    # Conversation state helpers
    def set_conversation_state(self, correlation_id: str, data: Dict[str, Any]):
        with self._lock:
            self.conversation_state[correlation_id] = data

    def get_conversation_state(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        return self.conversation_state.get(correlation_id)

# Singleton for simplicity in Phase 1
GLOBAL_DB = InMemoryDB()
