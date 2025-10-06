from __future__ import annotations
from typing import Dict, Type, Any
from pydantic import BaseModel, ValidationError
from state.event_log import log
from authz.engine import can as authz_can
from state.repository import GLOBAL_DB
from state.models import MessageOutboxItem, new_id, VolunteerRequest
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
from datetime import datetime

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
