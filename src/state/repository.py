from __future__ import annotations
from typing import Dict, List, Optional, Any, Iterable
from .models import (
    EventLogEntry,
    VolunteerRequest,
    RoomHold,
    MessageOutboxItem,
    IdempotencyRecord,
    ShardLock,
    GuestConnectionVolunteer,
    GuestConnectionRequest,
    ConversationMessage,
    new_id,
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
        self.guest_connection_volunteers: Dict[str, GuestConnectionVolunteer] = {}
        self.guest_connection_requests: Dict[str, GuestConnectionRequest] = {}
        # Conversation state (ephemeral) keyed by correlation_id
        self.conversation_state: Dict[str, Dict[str, Any]] = {}
        self.conversation_history: Dict[str, List[ConversationMessage]] = {}
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

    # Guest connection volunteers
    def save_guest_connection_volunteer(self, volunteer: GuestConnectionVolunteer):
        with self._lock:
            volunteer.updated_at = _NOW()
            self.guest_connection_volunteers[volunteer.id] = volunteer

    def get_guest_connection_volunteer(self, volunteer_id: str) -> Optional[GuestConnectionVolunteer]:
        return self.guest_connection_volunteers.get(volunteer_id)

    def find_guest_connection_volunteer_by_phone(self, tenant_id: str, phone: str) -> Optional[GuestConnectionVolunteer]:
        for vol in self.guest_connection_volunteers.values():
            if vol.tenant_id == tenant_id and vol.phone == phone:
                return vol
        return None

    def list_active_guest_connection_volunteers(self, tenant_id: str) -> List[GuestConnectionVolunteer]:
        return [
            vol
            for vol in self.guest_connection_volunteers.values()
            if vol.tenant_id == tenant_id and vol.active
        ]

    # Guest connection requests
    def save_guest_connection_request(self, request: GuestConnectionRequest):
        with self._lock:
            request.updated_at = _NOW()
            self.guest_connection_requests[request.id] = request

    def get_guest_connection_request(self, request_id: str) -> Optional[GuestConnectionRequest]:
        return self.guest_connection_requests.get(request_id)

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

    # Conversation history helpers
    def _history_key(self, tenant_id: str, actor_id: str) -> str:
        return f"{tenant_id}::{actor_id}"

    def append_conversation_message(self, tenant_id: str, actor_id: str, role: str, content: str) -> ConversationMessage:
        with self._lock:
            key = self._history_key(tenant_id, actor_id)
            history = self.conversation_history.setdefault(key, [])
            message = ConversationMessage(
                id=new_id(),
                tenant_id=tenant_id,
                actor_id=actor_id,
                role=role,
                content=content,
                timestamp=_NOW(),
            )
            history.append(message)
            # keep only the latest 50 messages per conversation to cap memory
            if len(history) > 50:
                del history[: len(history) - 50]
            return message

    def get_conversation_history(self, tenant_id: str, actor_id: str, limit: Optional[int] = 10) -> List[ConversationMessage]:
        key = self._history_key(tenant_id, actor_id)
        history = self.conversation_history.get(key, [])
        if not limit or limit >= len(history):
            return list(history)
        return history[-limit:]

# Singleton for simplicity in Phase 1
GLOBAL_DB = InMemoryDB()
