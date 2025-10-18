from __future__ import annotations
from typing import Dict, List, Optional, Any
import os
import uuid
import logging
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
from psycopg_pool import ConnectionPool
from psycopg.types.json import Json
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

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

    def list_guest_connection_volunteers(
        self,
        tenant_id: str,
        *,
        active: Optional[bool] = None,
        only_available: bool = False,
    ) -> List[GuestConnectionVolunteer]:
        with self._lock:
            volunteers = [
                vol
                for vol in self.guest_connection_volunteers.values()
                if vol.tenant_id == tenant_id
                and (active is None or vol.active == active)
                and (not only_available or not vol.currently_assigned_request_id)
            ]
        volunteers.sort(
            key=lambda v: (
                0 if v.last_matched_at is None else 1,
                v.last_matched_at or datetime.fromtimestamp(0),
                v.created_at,
                v.id,
            )
        )
        return volunteers

    def list_active_guest_connection_volunteers(self, tenant_id: str) -> List[GuestConnectionVolunteer]:
        return self.list_guest_connection_volunteers(tenant_id, active=True, only_available=False)

    # Guest connection requests
    def save_guest_connection_request(self, request: GuestConnectionRequest):
        with self._lock:
            request.updated_at = _NOW()
            self.guest_connection_requests[request.id] = request

    def get_guest_connection_request(self, request_id: str) -> Optional[GuestConnectionRequest]:
        return self.guest_connection_requests.get(request_id)

    def list_guest_connection_requests(
        self,
        tenant_id: str,
        *,
        status: Optional[str] = None,
        assigned: Optional[bool] = None,
    ) -> List[GuestConnectionRequest]:
        with self._lock:
            requests = [
                req
                for req in self.guest_connection_requests.values()
                if req.tenant_id == tenant_id
                and (status is None or req.status == status)
                and (
                    assigned is None
                    or (assigned and req.volunteer_id)
                    or (assigned is False and not req.volunteer_id)
                )
            ]
        requests.sort(key=lambda r: (r.created_at, r.id))
        return requests

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

    def get_person_profile(self, entity_id: str) -> Optional[dict]:
        return None

class PostgresBackedDB(InMemoryDB):
    """Hybrid DB that persists conversation history to Postgres while
    preserving in-memory behaviour for the rest of the app."""

    def __init__(self, conninfo: str):
        super().__init__()
        self._logger = logging.getLogger("state.postgres")
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
            self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)
        self._pool = ConnectionPool(
            conninfo,
            min_size=1,
            max_size=5,
            kwargs={"autocommit": True},
        )

    @staticmethod
    def _safe_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
        if not value:
            return None
        try:
            return uuid.UUID(value)
        except (ValueError, TypeError):
            return None

    def _get_conversation_id(self, conn, tenant_id: str, actor_id: str, create: bool) -> Optional[uuid.UUID]:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id
                from conversation
                where tenant_id = %s
                  and topic = %s
                  and deleted_at is null
                order by created_at desc
                limit 1
                """,
                (tenant_id, actor_id),
            )
            row = cur.fetchone()
            if row:
                return row[0]
            if not create:
                return None
            conversation_id = uuid.uuid4()
            cur.execute(
                """
                insert into conversation (id, tenant_id, topic, channel, state)
                values (%s, %s, %s, %s, %s)
                """,
                (
                    conversation_id,
                    tenant_id,
                    actor_id,
                    "cli",
                    "active",
                ),
            )
            return conversation_id

    def append_conversation_message(self, tenant_id: str, actor_id: str, role: str, content: str) -> ConversationMessage:
        timestamp = _NOW()
        try:
            with self._pool.connection() as conn:
                conversation_id = self._get_conversation_id(conn, tenant_id, actor_id, create=True)
                if not conversation_id:
                    raise RuntimeError("Failed to ensure conversation row")
                message_id = uuid.uuid4()
                direction = "inbound" if role == "user" else "outbound"
                sent_at = timestamp if direction == "outbound" else None
                received_at = timestamp if direction == "inbound" else None
                metadata = Json({"role": role})
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        insert into message_log (
                            id,
                            conversation_id,
                            tenant_id,
                            from_entity_id,
                            to_entity_id,
                            direction,
                            channel,
                            body,
                            status,
                            metadata_json,
                            sent_at,
                            received_at
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            message_id,
                            conversation_id,
                            tenant_id,
                            None,
                            None,
                            direction,
                            "cli",
                            content,
                            "delivered",
                            metadata,
                            sent_at,
                            received_at,
                        ),
                    )
                    cur.execute(
                        "update conversation set updated_at = now() where id = %s",
                        (conversation_id,),
                    )
                return ConversationMessage(
                    id=message_id.hex,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    role=role,
                    content=content,
                    timestamp=timestamp,
                )
        except Exception:  # noqa: BLE001 - fallback to in-memory store
            self._logger.exception("Falling back to in-memory conversation store")
            return super().append_conversation_message(tenant_id, actor_id, role, content)

    def get_conversation_history(self, tenant_id: str, actor_id: str, limit: Optional[int] = 10) -> List[ConversationMessage]:
        try:
            with self._pool.connection() as conn:
                conversation_id = self._get_conversation_id(conn, tenant_id, actor_id, create=False)
                if not conversation_id:
                    return []
                params: list[Any] = [conversation_id]
                limit_clause = ""
                if limit:
                    limit_clause = " limit %s"
                    params.append(limit)
                query = f"""
                    select id, body, metadata_json, created_at
                    from message_log
                    where conversation_id = %s
                    order by created_at desc{limit_clause}
                """
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()
                messages: List[ConversationMessage] = []
                for row in reversed(rows):
                    meta = row.get("metadata_json") or {}
                    role = meta.get("role", "user")
                    msg_id = row["id"]
                    if isinstance(msg_id, uuid.UUID):
                        msg_id = msg_id.hex
                    messages.append(
                        ConversationMessage(
                            id=msg_id,
                            tenant_id=tenant_id,
                            actor_id=actor_id,
                            role=role,
                            content=row["body"],
                            timestamp=row["created_at"],
                        )
                    )
                return messages
        except Exception:  # noqa: BLE001 - fallback to memory
            self._logger.exception("Falling back to in-memory history fetch")
            return super().get_conversation_history(tenant_id, actor_id, limit)

    def get_person_profile(self, entity_id: str) -> Optional[dict]:
        try:
            entity_uuid = self._safe_uuid(entity_id)
            if not entity_uuid:
                raise ValueError("Invalid entity identifier")
            with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    select
                        p.first_name,
                        p.last_name,
                        p.gender,
                        p.dob,
                        p.contact_json,
                        p.tenant_id,
                        ph.role_in_household,
                        h.name as household_name
                    from person p
                    left join person_household ph
                        on ph.person_id = p.entity_id
                        and ph.is_primary = true
                    left join household h
                        on h.id = ph.household_id
                    where p.entity_id = %s
                    """,
                    (entity_uuid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                profile = {
                    "tenant_id": str(row["tenant_id"]),
                    "first_name": row["first_name"],
                    "last_name": row["last_name"],
                    "gender": row["gender"],
                    "dob": row["dob"],
                    "contact": row["contact_json"] or {},
                    "household_role": row["role_in_household"],
                    "household_name": row["household_name"],
                }
                return profile
        except Exception:
            self._logger.exception("Falling back to in-memory person lookup")
        return super().get_person_profile(entity_id)

    # Guest connection volunteers
    def save_guest_connection_volunteer(self, volunteer: GuestConnectionVolunteer):
        volunteer.updated_at = _NOW()
        try:
            with self._pool.connection() as conn, conn.cursor() as cur:
                volunteer_uuid = self._safe_uuid(volunteer.id)
                tenant_uuid = self._safe_uuid(volunteer.tenant_id)
                assigned_uuid = self._safe_uuid(volunteer.currently_assigned_request_id)
                if not volunteer_uuid or not tenant_uuid:
                    raise ValueError("Invalid volunteer identifiers")
                cur.execute(
                    """
                    insert into guest_connection_volunteer (
                        id,
                        tenant_id,
                        name,
                        phone,
                        age_range,
                        gender,
                        marital_status,
                        active,
                        currently_assigned_request_id,
                        last_matched_at,
                        created_at,
                        updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (id) do update set
                        name = excluded.name,
                        phone = excluded.phone,
                        age_range = excluded.age_range,
                        gender = excluded.gender,
                        marital_status = excluded.marital_status,
                        active = excluded.active,
                        currently_assigned_request_id = excluded.currently_assigned_request_id,
                        last_matched_at = excluded.last_matched_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        volunteer_uuid,
                        tenant_uuid,
                        volunteer.name,
                        volunteer.phone,
                        volunteer.age_range,
                        volunteer.gender,
                        volunteer.marital_status,
                        volunteer.active,
                        assigned_uuid,
                        volunteer.last_matched_at,
                        volunteer.created_at,
                        volunteer.updated_at,
                    ),
                )
        except Exception:
            self._logger.exception("Falling back to in-memory volunteer save")
            return super().save_guest_connection_volunteer(volunteer)
        self.guest_connection_volunteers[volunteer.id] = volunteer
        return volunteer

    def get_guest_connection_volunteer(self, volunteer_id: str) -> Optional[GuestConnectionVolunteer]:
        try:
            volunteer_uuid = self._safe_uuid(volunteer_id)
            if not volunteer_uuid:
                raise ValueError("Invalid volunteer identifier")
            with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    select *
                    from guest_connection_volunteer
                    where id = %s
                    """,
                    (volunteer_uuid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                volunteer = GuestConnectionVolunteer(
                    id=volunteer_id,
                    tenant_id=str(row["tenant_id"]),
                    name=row["name"],
                    phone=row["phone"],
                    age_range=row["age_range"],
                    gender=row["gender"],
                    marital_status=row["marital_status"],
                    active=row["active"],
                    currently_assigned_request_id=str(row["currently_assigned_request_id"]) if row["currently_assigned_request_id"] else None,
                    last_matched_at=row["last_matched_at"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                self.guest_connection_volunteers[volunteer.id] = volunteer
                return volunteer
        except Exception:
            self._logger.exception("Falling back to in-memory volunteer fetch")
        return super().get_guest_connection_volunteer(volunteer_id)

    def find_guest_connection_volunteer_by_phone(self, tenant_id: str, phone: str) -> Optional[GuestConnectionVolunteer]:
        try:
            tenant_uuid = self._safe_uuid(tenant_id)
            if not tenant_uuid:
                raise ValueError("Invalid tenant identifier")
            with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    select *
                    from guest_connection_volunteer
                    where tenant_id = %s
                      and phone = %s
                    """,
                    (tenant_uuid, phone),
                )
                row = cur.fetchone()
                if not row:
                    return None
                volunteer = GuestConnectionVolunteer(
                    id=str(row["id"]),
                    tenant_id=tenant_id,
                    name=row["name"],
                    phone=row["phone"],
                    age_range=row["age_range"],
                    gender=row["gender"],
                    marital_status=row["marital_status"],
                    active=row["active"],
                    currently_assigned_request_id=str(row["currently_assigned_request_id"]) if row["currently_assigned_request_id"] else None,
                    last_matched_at=row["last_matched_at"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                self.guest_connection_volunteers[volunteer.id] = volunteer
                return volunteer
        except Exception:
            self._logger.exception("Falling back to in-memory volunteer search")
        return super().find_guest_connection_volunteer_by_phone(tenant_id, phone)

    def list_guest_connection_volunteers(
        self,
        tenant_id: str,
        *,
        active: Optional[bool] = None,
        only_available: bool = False,
    ) -> List[GuestConnectionVolunteer]:
        try:
            tenant_uuid = self._safe_uuid(tenant_id)
            if not tenant_uuid:
                raise ValueError("Invalid tenant identifier")
            with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                filters: list[str] = ["tenant_id = %s"]
                params: list[Any] = [tenant_uuid]
                if active is not None:
                    filters.append("active = %s")
                    params.append(active)
                if only_available:
                    filters.append("currently_assigned_request_id is null")
                where_clause = " and ".join(filters)
                query = (
                    """
                    select *
                    from guest_connection_volunteer
                    where """
                    + where_clause
                    + """
                    order by coalesce(last_matched_at, to_timestamp(0)), created_at
                    """
                )
                cur.execute(query, params)
                rows = cur.fetchall()
                volunteers: List[GuestConnectionVolunteer] = []
                for row in rows:
                    volunteer = GuestConnectionVolunteer(
                        id=str(row["id"]),
                        tenant_id=tenant_id,
                        name=row["name"],
                        phone=row["phone"],
                        age_range=row["age_range"],
                        gender=row["gender"],
                        marital_status=row["marital_status"],
                        active=row["active"],
                        currently_assigned_request_id=str(row["currently_assigned_request_id"]) if row["currently_assigned_request_id"] else None,
                        last_matched_at=row["last_matched_at"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                    self.guest_connection_volunteers[volunteer.id] = volunteer
                    volunteers.append(volunteer)
                return volunteers
        except Exception:
            self._logger.exception("Falling back to in-memory volunteer list")
        return super().list_guest_connection_volunteers(
            tenant_id,
            active=active,
            only_available=only_available,
        )

    def list_active_guest_connection_volunteers(self, tenant_id: str) -> List[GuestConnectionVolunteer]:
        return self.list_guest_connection_volunteers(tenant_id, active=True, only_available=False)

    # Guest connection requests
    def save_guest_connection_request(self, request: GuestConnectionRequest):
        request.updated_at = _NOW()
        try:
            with self._pool.connection() as conn, conn.cursor() as cur:
                request_uuid = self._safe_uuid(request.id)
                tenant_uuid = self._safe_uuid(request.tenant_id)
                volunteer_uuid = self._safe_uuid(request.volunteer_id)
                if not request_uuid or not tenant_uuid:
                    raise ValueError("Invalid request identifiers")
                cur.execute(
                    """
                    insert into guest_connection_request (
                        id,
                        tenant_id,
                        guest_name,
                        contact,
                        age_range,
                        gender,
                        marital_status,
                        status,
                        volunteer_id,
                        notes,
                        created_at,
                        updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (id) do update set
                        guest_name = excluded.guest_name,
                        contact = excluded.contact,
                        age_range = excluded.age_range,
                        gender = excluded.gender,
                        marital_status = excluded.marital_status,
                        status = excluded.status,
                        volunteer_id = excluded.volunteer_id,
                        notes = excluded.notes,
                        updated_at = excluded.updated_at
                    """,
                    (
                        request_uuid,
                        tenant_uuid,
                        request.guest_name,
                        request.contact,
                        request.age_range,
                        request.gender,
                        request.marital_status,
                        request.status,
                        volunteer_uuid,
                        request.notes,
                        request.created_at,
                        request.updated_at,
                    ),
                )
        except Exception:
            self._logger.exception("Falling back to in-memory request save")
            return super().save_guest_connection_request(request)
        self.guest_connection_requests[request.id] = request
        return request

    def list_guest_connection_requests(
        self,
        tenant_id: str,
        *,
        status: Optional[str] = None,
        assigned: Optional[bool] = None,
    ) -> List[GuestConnectionRequest]:
        try:
            tenant_uuid = self._safe_uuid(tenant_id)
            if not tenant_uuid:
                raise ValueError("Invalid tenant identifier")
            with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                filters: list[str] = ["tenant_id = %s"]
                params: list[Any] = [tenant_uuid]
                if status:
                    filters.append("status = %s")
                    params.append(status)
                if assigned is not None:
                    if assigned:
                        filters.append("volunteer_id is not null")
                    else:
                        filters.append("volunteer_id is null")
                where_clause = " and ".join(filters)
                query = (
                    """
                    select *
                    from guest_connection_request
                    where """
                    + where_clause
                    + """
                    order by created_at
                    """
                )
                cur.execute(query, params)
                rows = cur.fetchall()
                requests: List[GuestConnectionRequest] = []
                for row in rows:
                    request = GuestConnectionRequest(
                        id=str(row["id"]),
                        tenant_id=str(row["tenant_id"]),
                        guest_name=row["guest_name"],
                        contact=row["contact"],
                        age_range=row["age_range"],
                        gender=row["gender"],
                        marital_status=row["marital_status"],
                        status=row["status"],
                        volunteer_id=str(row["volunteer_id"]) if row["volunteer_id"] else None,
                        notes=row["notes"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                    self.guest_connection_requests[request.id] = request
                    requests.append(request)
                return requests
        except Exception:
            self._logger.exception("Falling back to in-memory request list")
        return super().list_guest_connection_requests(tenant_id, status=status, assigned=assigned)

    def get_guest_connection_request(self, request_id: str) -> Optional[GuestConnectionRequest]:
        try:
            with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    select *
                    from guest_connection_request
                    where id = %s
                    """,
                    (self._safe_uuid(request_id),),
                )
                row = cur.fetchone()
                if not row:
                    return None
                request = GuestConnectionRequest(
                    id=request_id,
                    tenant_id=str(row["tenant_id"]),
                    guest_name=row["guest_name"],
                    contact=row["contact"],
                    age_range=row["age_range"],
                    gender=row["gender"],
                    marital_status=row["marital_status"],
                    status=row["status"],
                    volunteer_id=str(row["volunteer_id"]) if row["volunteer_id"] else None,
                    notes=row["notes"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                self.guest_connection_requests[request.id] = request
                return request
        except Exception:
            self._logger.exception("Falling back to in-memory request fetch")
        return super().get_guest_connection_request(request_id)


def _initialise_db() -> InMemoryDB:
    logger = logging.getLogger("state.repository")
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    conninfo = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_DEV")
    if conninfo:
        try:
            source = "DATABASE_URL" if os.getenv("DATABASE_URL") else "DATABASE_URL_DEV"
            logger.info("Using PostgresBackedDB for conversation history via %s", source)
            return PostgresBackedDB(conninfo)
        except Exception:  # noqa: BLE001
            logger.exception("Unable to initialise PostgresBackedDB; falling back to in-memory store")
    else:
        logger.info("DATABASE_URL not set; using in-memory store")
    return InMemoryDB()

# Singleton for simplicity in Phase 1
GLOBAL_DB = _initialise_db()
