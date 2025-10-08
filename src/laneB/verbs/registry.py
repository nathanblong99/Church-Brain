from __future__ import annotations
from typing import Dict, Type, Any
from pydantic import BaseModel, ValidationError
from state.event_log import log
from authz.engine import can as authz_can
from state.repository import GLOBAL_DB
from state.models import (
    MessageOutboxItem,
    new_id,
    VolunteerRequest,
    GuestConnectionVolunteer,
    GuestConnectionRequest,
)
from datetime import datetime

class VerbContext(BaseModel):
    correlation_id: str
    tenant_id: str
    actor_id: str
    actor_roles: list[str]
    shard: str | None = None

class VerbResult(BaseModel):
    ok: bool
    data: Any | None = None
    error: str | None = None

class BaseVerb:
    name: str = "base"
    schema: Type[BaseModel] = BaseModel
    authz_action: str | None = None

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        raise NotImplementedError

VERBS: Dict[str, Type[BaseVerb]] = {}

def register(verb: Type[BaseVerb]):
    VERBS[verb.name] = verb
    return verb

# ---- Verb Implementations ----

class PeopleSearchArgs(BaseModel):
    query: str

@register
class PeopleSearchVerb(BaseVerb):
    name = "people.search"
    schema = PeopleSearchArgs
    authz_action = "planning.create"  # read-level for now

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        # Placeholder: return dummy people
        q = args["query"].lower()
        people = [
            {"id": "p1", "name": "Alice", "skills": ["basketball"]},
            {"id": "p2", "name": "Bob", "skills": ["volleyball"]},
            {"id": "p3", "name": "Cara", "skills": ["basketball", "volleyball"]},
        ]
        filtered = [p for p in people if q in p["name"].lower() or q in ",".join(p["skills"]) ]
        return VerbResult(ok=True, data=filtered)

class MakeOffersArgs(BaseModel):
    request_id: str
    candidates: list[str]
    role: str

@register
class MakeOffersVerb(BaseVerb):
    name = "make_offers"
    schema = MakeOffersArgs
    authz_action = "volunteer.manage"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        # For Phase 1 we just log offers (no persistence of offers object)
        log("offers_made", ctx.correlation_id, ctx.actor_id, ctx.tenant_id, ctx.shard, {"args": args})
        return VerbResult(ok=True, data={"offers": args["candidates"]})

class AssignArgs(BaseModel):
    request_id: str
    person_id: str
    role: str

@register
class AssignVerb(BaseVerb):
    name = "assign"
    schema = AssignArgs
    authz_action = "volunteer.manage"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        req = GLOBAL_DB.volunteer_requests.get(args["request_id"])
        if not req:
            return VerbResult(ok=False, error="request_not_found")
        if args["person_id"] in req.assignments.get(args["role"], []):
            return VerbResult(ok=True, data="already_assigned")
        req.assignments.setdefault(args["role"], []).append(args["person_id"])
        GLOBAL_DB.save_volunteer_request(req)
        return VerbResult(ok=True, data={"assignments": req.assignments})

class UnassignArgs(BaseModel):
    request_id: str
    person_id: str
    role: str

@register
class UnassignVerb(BaseVerb):
    name = "unassign"
    schema = UnassignArgs
    authz_action = "volunteer.manage"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        req = GLOBAL_DB.volunteer_requests.get(args["request_id"])
        if not req:
            return VerbResult(ok=False, error="request_not_found")
        if args["person_id"] in req.assignments.get(args["role"], []):
            req.assignments[args["role"].replace("\\n", "")].remove(args["person_id"])
            GLOBAL_DB.save_volunteer_request(req)
        return VerbResult(ok=True, data={"assignments": req.assignments})

class SmsSendArgs(BaseModel):
    to: str
    template: str
    variables: dict
    idempotency_key: str

@register
class SmsSendVerb(BaseVerb):
    name = "sms.send"
    schema = SmsSendArgs
    authz_action = "message.send"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        # Dev adapter: record to outbox only
        if GLOBAL_DB.has_idempotency_key(args["idempotency_key"]):
            return VerbResult(ok=True, data="duplicate_suppressed")
        item = MessageOutboxItem(
            id=new_id(),
            tenant_id=ctx.tenant_id,
            channel="sms",
            to=args["to"],
            template=args["template"],
            variables=args["variables"],
            idempotency_key=args["idempotency_key"],
        )
        GLOBAL_DB.record_outbox_item(item)
        return VerbResult(ok=True, data={"outbox_id": item.id})

class EmailSendArgs(BaseModel):
    to: str
    template: str
    variables: dict
    idempotency_key: str

@register
class EmailSendVerb(BaseVerb):
    name = "email.send"
    schema = EmailSendArgs
    authz_action = "message.send"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        if GLOBAL_DB.has_idempotency_key(args["idempotency_key"]):
            return VerbResult(ok=True, data="duplicate_suppressed")
        item = MessageOutboxItem(
            id=new_id(),
            tenant_id=ctx.tenant_id,
            channel="email",
            to=args["to"],
            template=args["template"],
            variables=args["variables"],
            idempotency_key=args["idempotency_key"],
        )
        GLOBAL_DB.record_outbox_item(item)
        return VerbResult(ok=True, data={"outbox_id": item.id})

class NotifyStaffArgs(BaseModel):
    staff_role: str
    template: str
    variables: dict

@register
class NotifyStaffVerb(BaseVerb):
    name = "notify.staff"
    schema = NotifyStaffArgs
    authz_action = "message.send"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        # Dev: just log
        return VerbResult(ok=True, data={"notified_role": args["staff_role"]})

class CreateRecordArgs(BaseModel):
    kind: str
    data: dict

@register
class CreateRecordVerb(BaseVerb):
    name = "create_record"
    schema = CreateRecordArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        if args["kind"] == "volunteer_request":
            req = VolunteerRequest(id=new_id(), tenant_id=ctx.tenant_id, basketball_needed=args["data"].get("basketball_needed",0), volleyball_needed=args["data"].get("volleyball_needed",0))
            GLOBAL_DB.save_volunteer_request(req)
            return VerbResult(ok=True, data={"id": req.id})
        return VerbResult(ok=False, error="unknown_kind")

class UpdateRecordArgs(BaseModel):
    kind: str
    id: str
    data: dict

@register
class UpdateRecordVerb(BaseVerb):
    name = "update_record"
    schema = UpdateRecordArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        if args["kind"] == "volunteer_request":
            req = GLOBAL_DB.volunteer_requests.get(args["id"])
            if not req:
                return VerbResult(ok=False, error="not_found")
            for k,v in args["data"].items():
                if hasattr(req, k):
                    setattr(req, k, v)
            GLOBAL_DB.save_volunteer_request(req)
            return VerbResult(ok=True, data={"id": req.id})
        return VerbResult(ok=False, error="unknown_kind")

class GuestVolunteerRegisterArgs(BaseModel):
    name: str
    phone: str
    age_range: str
    gender: str
    marital_status: str
    active: bool | None = True

@register
class GuestVolunteerRegisterVerb(BaseVerb):
    name = "guest_pairing.volunteer_register"
    schema = GuestVolunteerRegisterArgs
    authz_action = None  # allow guests to opt-in

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        phone = args["phone"].strip()
        existing = GLOBAL_DB.find_guest_connection_volunteer_by_phone(ctx.tenant_id, phone)
        if existing:
            existing.name = args["name"]
            existing.age_range = args["age_range"]
            existing.gender = args["gender"]
            existing.marital_status = args["marital_status"]
            if args.get("active") is not None:
                existing.active = args["active"]
            existing.phone = phone
            GLOBAL_DB.save_guest_connection_volunteer(existing)
            return VerbResult(ok=True, data={"volunteer_id": existing.id, "status": "updated"})
        volunteer = GuestConnectionVolunteer(
            id=new_id(),
            tenant_id=ctx.tenant_id,
            name=args["name"],
            phone=phone,
            age_range=args["age_range"],
            gender=args["gender"],
            marital_status=args["marital_status"],
            active=args.get("active", True),
        )
        GLOBAL_DB.save_guest_connection_volunteer(volunteer)
        return VerbResult(ok=True, data={"volunteer_id": volunteer.id, "status": "created"})

class GuestRequestCreateArgs(BaseModel):
    guest_name: str
    contact: str
    age_range: str
    gender: str
    marital_status: str
    notes: str | None = None

@register
class GuestRequestCreateVerb(BaseVerb):
    name = "guest_pairing.request_create"
    schema = GuestRequestCreateArgs
    authz_action = None  # allow curious guests to request pairing

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        request = GuestConnectionRequest(
            id=new_id(),
            tenant_id=ctx.tenant_id,
            guest_name=args["guest_name"],
            contact=args["contact"],
            age_range=args["age_range"],
            gender=args["gender"],
            marital_status=args["marital_status"],
            notes=args.get("notes"),
        )
        GLOBAL_DB.save_guest_connection_request(request)
        return VerbResult(ok=True, data={"request_id": request.id})

class GuestMatchArgs(BaseModel):
    request_id: str
    limit: int = 3

@register
class GuestMatchVerb(BaseVerb):
    name = "guest_pairing.match"
    schema = GuestMatchArgs
    authz_action = "volunteer.manage"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        request = GLOBAL_DB.get_guest_connection_request(args["request_id"])
        if not request:
            return VerbResult(ok=False, error="guest_request_not_found")
        if request.tenant_id != ctx.tenant_id:
            return VerbResult(ok=False, error="tenant_mismatch")
        volunteers = GLOBAL_DB.list_active_guest_connection_volunteers(ctx.tenant_id)
        candidates: list[tuple[int, GuestConnectionVolunteer]] = []
        for vol in volunteers:
            if vol.currently_assigned_request_id and vol.currently_assigned_request_id != request.id:
                continue
            score = 0
            if vol.age_range == request.age_range:
                score += 1
            if vol.gender == request.gender:
                score += 1
            if vol.marital_status == request.marital_status:
                score += 1
            candidates.append((score, vol))
        if not candidates:
            return VerbResult(ok=True, data={"matches": []})
        def sort_key(item: tuple[int, GuestConnectionVolunteer]):
            score, vol = item
            last = vol.last_matched_at or datetime.fromtimestamp(0)
            created = vol.created_at
            reassigned_bias = 0 if vol.currently_assigned_request_id == request.id else 1
            return (-score, reassigned_bias, last, created, vol.id)
        candidates.sort(key=sort_key)
        limit = max(1, min(args.get("limit", 3), 10))
        matches = []
        for score, vol in candidates[:limit]:
            matches.append({
                "volunteer_id": vol.id,
                "name": vol.name,
                "phone": vol.phone,
                "age_range": vol.age_range,
                "gender": vol.gender,
                "marital_status": vol.marital_status,
                "score": score,
                "currently_assigned": vol.currently_assigned_request_id == request.id,
            })
        return VerbResult(ok=True, data={"matches": matches})

class GuestAssignArgs(BaseModel):
    request_id: str
    volunteer_id: str

@register
class GuestAssignVerb(BaseVerb):
    name = "guest_pairing.assign"
    schema = GuestAssignArgs
    authz_action = "volunteer.manage"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        request = GLOBAL_DB.get_guest_connection_request(args["request_id"])
        if not request:
            return VerbResult(ok=False, error="guest_request_not_found")
        if request.tenant_id != ctx.tenant_id:
            return VerbResult(ok=False, error="tenant_mismatch")
        volunteer = GLOBAL_DB.get_guest_connection_volunteer(args["volunteer_id"])
        if not volunteer or volunteer.tenant_id != ctx.tenant_id:
            return VerbResult(ok=False, error="volunteer_not_found")
        if not volunteer.active:
            return VerbResult(ok=False, error="volunteer_inactive")
        if request.status == "CLOSED":
            return VerbResult(ok=False, error="request_closed")
        if volunteer.currently_assigned_request_id and volunteer.currently_assigned_request_id != request.id:
            return VerbResult(ok=False, error="volunteer_already_assigned")
        # release previously matched volunteer if different
        if request.volunteer_id and request.volunteer_id != volunteer.id:
            previous = GLOBAL_DB.get_guest_connection_volunteer(request.volunteer_id)
            if previous and previous.currently_assigned_request_id == request.id:
                previous.currently_assigned_request_id = None
                GLOBAL_DB.save_guest_connection_volunteer(previous)
        request.volunteer_id = volunteer.id
        request.status = "MATCHED"
        GLOBAL_DB.save_guest_connection_request(request)
        volunteer.currently_assigned_request_id = request.id
        volunteer.last_matched_at = datetime.utcnow()
        GLOBAL_DB.save_guest_connection_volunteer(volunteer)
        return VerbResult(ok=True, data={"request_id": request.id, "volunteer_id": volunteer.id})

class ScheduleTimerArgs(BaseModel):
    delay_seconds: int
    payload: dict

@register
class ScheduleTimerVerb(BaseVerb):
    name = "schedule.timer"
    schema = ScheduleTimerArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        # Phase 1: no real scheduler, just echo
        return VerbResult(ok=True, data={"scheduled_in": args["delay_seconds"]})

# Placeholder catalog.run
class CatalogRunArgs(BaseModel):
    op: str
    params: dict

@register
class CatalogRunVerb(BaseVerb):
    name = "catalog.run"
    schema = CatalogRunArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        # Lane A placeholder; return nothing
        return VerbResult(ok=True, data={"rows": []})

# ---- Room Allocation Verbs (Phase 1 skeleton) ----
from allocator import allocator as _alloc

class RoomHoldArgs(BaseModel):
    room_id: str
    start_iso: str
    end_iso: str

@register
class RoomHoldVerb(BaseVerb):
    name = "room.hold"
    schema = RoomHoldArgs
    authz_action = "room.allocate"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        try:
            start = datetime.fromisoformat(args["start_iso"])
            end = datetime.fromisoformat(args["end_iso"])
        except ValueError:
            return VerbResult(ok=False, error="invalid_time_format")
        ok, hold, reason = _alloc.room_hold(ctx.tenant_id, args["room_id"], start, end)
        if not ok:
            return VerbResult(ok=False, error=reason)
        return VerbResult(ok=True, data={"hold_id": hold.id, "status": hold.status})

class RoomAdjustArgs(BaseModel):
    hold_id: str
    start_iso: str
    end_iso: str

@register
class RoomAdjustVerb(BaseVerb):
    name = "room.adjust"
    schema = RoomAdjustArgs
    authz_action = "room.allocate"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        try:
            start = datetime.fromisoformat(args["start_iso"])
            end = datetime.fromisoformat(args["end_iso"])
        except ValueError:
            return VerbResult(ok=False, error="invalid_time_format")
        ok, reason = _alloc.adjust_hold(args["hold_id"], start, end)
        if not ok:
            return VerbResult(ok=False, error=reason)
        return VerbResult(ok=True, data={"hold_id": args["hold_id"], "status": "ADJUSTED"})

class RoomConfirmArgs(BaseModel):
    hold_id: str

@register
class RoomConfirmVerb(BaseVerb):
    name = "room.confirm"
    schema = RoomConfirmArgs
    authz_action = "room.allocate"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        ok, reason = _alloc.room_confirm(args["hold_id"])
        if not ok:
            return VerbResult(ok=False, error=reason)
        return VerbResult(ok=True, data={"hold_id": args["hold_id"], "status": "CONFIRMED"})

# ---- Execution Helper ----

def run_verb(verb_name: str, raw_args: dict, ctx: VerbContext) -> VerbResult:
    verb_cls = VERBS.get(verb_name)
    if not verb_cls:
        return VerbResult(ok=False, error="unknown_verb")
    # authz
    if verb_cls.authz_action:
        allowed, reason = authz_can(ctx.actor_roles, verb_cls.authz_action, None, {})
        if not allowed:
            log("authz_denied", ctx.correlation_id, ctx.actor_id, ctx.tenant_id, ctx.shard, {"verb": verb_name, "reason": reason})
            return VerbResult(ok=False, error=f"authz_denied:{reason}")
    # validate
    try:
        parsed = verb_cls.schema(**raw_args)
    except ValidationError as e:
        return VerbResult(ok=False, error=f"validation_error:{e}")
    result = verb_cls.execute(parsed.dict(), ctx)
    log("verb_executed", ctx.correlation_id, ctx.actor_id, ctx.tenant_id, ctx.shard, {"verb": verb_name, "ok": result.ok})
    return result
