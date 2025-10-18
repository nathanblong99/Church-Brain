from __future__ import annotations
from typing import Dict, Type, Any
from pydantic import BaseModel, ValidationError, Field
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


class ConversationReplyArgs(BaseModel):
    body: str
    channel: str | None = None
    metadata: dict[str, Any] | None = None


@register
class ConversationReplyVerb(BaseVerb):
    name = "conversation.reply"
    schema = ConversationReplyArgs
    authz_action = "message.send"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        message = GLOBAL_DB.append_conversation_message(ctx.tenant_id, ctx.actor_id, "assistant", args["body"])
        log(
            "conversation_reply",
            ctx.correlation_id,
            ctx.actor_id,
            ctx.tenant_id,
            ctx.shard,
            {"channel": args.get("channel"), "metadata": args.get("metadata")},
        )
        return VerbResult(
            ok=True,
            data={
                "message_id": message.id,
                "body": message.content,
                "timestamp": message.timestamp.isoformat(),
            },
        )


class ConversationNoteArgs(BaseModel):
    note: str
    visibility: str | None = None


@register
class ConversationNoteVerb(BaseVerb):
    name = "conversation.note"
    schema = ConversationNoteArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        state = GLOBAL_DB.get_conversation_state(ctx.correlation_id) or {}
        notes: list[dict[str, Any]] = list(state.get("notes", []))
        entry = {
            "note": args["note"],
            "visibility": args.get("visibility", "internal"),
            "timestamp": datetime.utcnow().isoformat(),
        }
        notes.append(entry)
        state["notes"] = notes
        GLOBAL_DB.set_conversation_state(ctx.correlation_id, state)
        log(
            "conversation_note",
            ctx.correlation_id,
            ctx.actor_id,
            ctx.tenant_id,
            ctx.shard,
            {"visibility": entry["visibility"]},
        )
        return VerbResult(ok=True, data={"notes": notes})


class ConversationTagArgs(BaseModel):
    tags: list[str]
    replace: bool = False


@register
class ConversationTagVerb(BaseVerb):
    name = "conversation.tag"
    schema = ConversationTagArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        state = GLOBAL_DB.get_conversation_state(ctx.correlation_id) or {}
        existing = set(state.get("tags", []))
        incoming = {tag.strip() for tag in args["tags"] if tag.strip()}
        tags = sorted(incoming if args.get("replace") else existing.union(incoming))
        state["tags"] = tags
        GLOBAL_DB.set_conversation_state(ctx.correlation_id, state)
        log(
            "conversation_tagged",
            ctx.correlation_id,
            ctx.actor_id,
            ctx.tenant_id,
            ctx.shard,
            {"tags": tags},
        )
        return VerbResult(ok=True, data={"tags": tags})


class ConversationStateGetArgs(BaseModel):
    keys: list[str] | None = None


@register
class ConversationStateGetVerb(BaseVerb):
    name = "conversation.state_get"
    schema = ConversationStateGetArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        state = GLOBAL_DB.get_conversation_state(ctx.correlation_id) or {}
        if args.get("keys"):
            subset = {key: state.get(key) for key in args["keys"]}
            return VerbResult(ok=True, data=subset)
        return VerbResult(ok=True, data=state)


class ConversationStateMergeArgs(BaseModel):
    data: dict
    replace: bool = False


@register
class ConversationStateMergeVerb(BaseVerb):
    name = "conversation.state_merge"
    schema = ConversationStateMergeArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        current = GLOBAL_DB.get_conversation_state(ctx.correlation_id) or {}
        incoming = args.get("data", {})
        if args.get("replace"):
            merged = dict(incoming)
        else:
            merged = {**current, **incoming}
        GLOBAL_DB.set_conversation_state(ctx.correlation_id, merged)
        log("conversation_state_updated", ctx.correlation_id, ctx.actor_id, ctx.tenant_id, ctx.shard, {"keys": list(incoming.keys())})
        return VerbResult(ok=True, data=merged)

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


class GuestRequestGetArgs(BaseModel):
    request_id: str


@register
class GuestRequestGetVerb(BaseVerb):
    name = "guest_request.get"
    schema = GuestRequestGetArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        request = GLOBAL_DB.get_guest_connection_request(args["request_id"])
        if not request or request.tenant_id != ctx.tenant_id:
            return VerbResult(ok=False, error="guest_request_not_found")
        return VerbResult(ok=True, data=_serialize_guest_request(request))


class GuestRequestListArgs(BaseModel):
    status: str | None = None
    assigned: bool | None = None
    limit: int | None = 10
    search: str | None = None


@register
class GuestRequestListVerb(BaseVerb):
    name = "guest_request.list"
    schema = GuestRequestListArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        requests = GLOBAL_DB.list_guest_connection_requests(
            ctx.tenant_id,
            status=args.get("status"),
            assigned=args.get("assigned"),
        )
        search = (args.get("search") or "").strip().lower()
        if search:
            requests = [
                req
                for req in requests
                if search in (req.guest_name or "").lower()
                or search in (req.contact or "").lower()
                or search in (req.notes or "").lower()
            ]
        limit = args.get("limit")
        if isinstance(limit, int) and limit >= 0:
            requests = requests[:limit] if limit else []
        data = [_serialize_guest_request(req) for req in requests]
        return VerbResult(ok=True, data={"requests": data})


class GuestRequestUpdateArgs(BaseModel):
    request_id: str
    changes: dict[str, Any] = Field(default_factory=dict)
    append_note: str | None = None


@register
class GuestRequestUpdateVerb(BaseVerb):
    name = "guest_request.update"
    schema = GuestRequestUpdateArgs
    authz_action = "volunteer.manage"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        request = GLOBAL_DB.get_guest_connection_request(args["request_id"])
        if not request or request.tenant_id != ctx.tenant_id:
            return VerbResult(ok=False, error="guest_request_not_found")
        changes = dict(args.get("changes") or {})
        append_note = args.get("append_note")
        if not changes and not append_note:
            return VerbResult(ok=False, error="no_changes_provided")
        allowed_fields = {
            "guest_name",
            "contact",
            "age_range",
            "gender",
            "marital_status",
            "status",
            "volunteer_id",
            "notes",
        }
        unknown = [key for key in changes if key not in allowed_fields]
        if unknown:
            return VerbResult(ok=False, error=f"unsupported_fields:{','.join(sorted(unknown))}")
        status = changes.get("status")
        if status and status not in {"OPEN", "MATCHED", "CLOSED"}:
            return VerbResult(ok=False, error="invalid_status")

        new_volunteer_id = changes.get("volunteer_id") if "volunteer_id" in changes else request.volunteer_id
        replacement_volunteer = None
        if "volunteer_id" in changes and new_volunteer_id:
            replacement_volunteer = GLOBAL_DB.get_guest_connection_volunteer(str(new_volunteer_id))
            if not replacement_volunteer or replacement_volunteer.tenant_id != ctx.tenant_id:
                return VerbResult(ok=False, error="volunteer_not_found")
            if not replacement_volunteer.active:
                return VerbResult(ok=False, error="volunteer_inactive")
            if (
                replacement_volunteer.currently_assigned_request_id
                and replacement_volunteer.currently_assigned_request_id != request.id
            ):
                return VerbResult(ok=False, error="volunteer_already_assigned")

        for field in ("guest_name", "contact", "age_range", "gender", "marital_status", "notes"):
            if field in changes:
                setattr(request, field, changes[field])

        if append_note:
            note = append_note.strip()
            if note:
                request.notes = f"{request.notes} | {note}" if request.notes else note

        old_volunteer_id = request.volunteer_id
        if "volunteer_id" in changes:
            if old_volunteer_id and old_volunteer_id != new_volunteer_id:
                previous = GLOBAL_DB.get_guest_connection_volunteer(old_volunteer_id)
                if previous and previous.currently_assigned_request_id == request.id:
                    previous.currently_assigned_request_id = None
                    GLOBAL_DB.save_guest_connection_volunteer(previous)
            if new_volunteer_id:
                assert replacement_volunteer is not None
                replacement_volunteer.currently_assigned_request_id = request.id
                replacement_volunteer.last_matched_at = datetime.utcnow()
                GLOBAL_DB.save_guest_connection_volunteer(replacement_volunteer)
                request.volunteer_id = replacement_volunteer.id
                if request.status == "OPEN" and "status" not in changes:
                    request.status = "MATCHED"
            else:
                request.volunteer_id = None
                if request.status == "MATCHED" and "status" not in changes:
                    request.status = "OPEN"

        if status:
            if status == "CLOSED" and request.volunteer_id:
                volunteer = GLOBAL_DB.get_guest_connection_volunteer(request.volunteer_id)
                if volunteer and volunteer.currently_assigned_request_id == request.id:
                    volunteer.currently_assigned_request_id = None
                    GLOBAL_DB.save_guest_connection_volunteer(volunteer)
                request.volunteer_id = None
            request.status = status

        GLOBAL_DB.save_guest_connection_request(request)
        log("guest_request_updated", ctx.correlation_id, ctx.actor_id, ctx.tenant_id, ctx.shard, {"request_id": request.id})
        return VerbResult(ok=True, data=_serialize_guest_request(request))


class GuestVolunteerGetArgs(BaseModel):
    volunteer_id: str


@register
class GuestVolunteerGetVerb(BaseVerb):
    name = "guest_volunteer.get"
    schema = GuestVolunteerGetArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        volunteer = GLOBAL_DB.get_guest_connection_volunteer(args["volunteer_id"])
        if not volunteer or volunteer.tenant_id != ctx.tenant_id:
            return VerbResult(ok=False, error="volunteer_not_found")
        return VerbResult(ok=True, data=_serialize_guest_volunteer(volunteer))


class GuestVolunteerListArgs(BaseModel):
    active: bool | None = None
    available_only: bool = False
    limit: int | None = 10
    search: str | None = None


@register
class GuestVolunteerListVerb(BaseVerb):
    name = "guest_volunteer.list"
    schema = GuestVolunteerListArgs
    authz_action = "planning.create"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        volunteers = GLOBAL_DB.list_guest_connection_volunteers(
            ctx.tenant_id,
            active=args.get("active"),
            only_available=args.get("available_only", False),
        )
        search = (args.get("search") or "").strip().lower()
        if search:
            volunteers = [
                vol
                for vol in volunteers
                if search in vol.name.lower()
                or search in vol.phone.lower()
                or search in (vol.gender or "").lower()
            ]
        limit = args.get("limit")
        if isinstance(limit, int) and limit >= 0:
            volunteers = volunteers[:limit] if limit else []
        data = [_serialize_guest_volunteer(vol) for vol in volunteers]
        return VerbResult(ok=True, data={"volunteers": data})


class GuestVolunteerUpdateArgs(BaseModel):
    volunteer_id: str
    changes: dict[str, Any] = Field(default_factory=dict)
    release_request: bool | None = None


@register
class GuestVolunteerUpdateVerb(BaseVerb):
    name = "guest_volunteer.update"
    schema = GuestVolunteerUpdateArgs
    authz_action = "volunteer.manage"

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        volunteer = GLOBAL_DB.get_guest_connection_volunteer(args["volunteer_id"])
        if not volunteer or volunteer.tenant_id != ctx.tenant_id:
            return VerbResult(ok=False, error="volunteer_not_found")
        changes = dict(args.get("changes") or {})
        if not changes and not args.get("release_request"):
            return VerbResult(ok=False, error="no_changes_provided")
        allowed_fields = {"name", "phone", "age_range", "gender", "marital_status", "active"}
        unknown = [key for key in changes if key not in allowed_fields]
        if unknown:
            return VerbResult(ok=False, error=f"unsupported_fields:{','.join(sorted(unknown))}")
        for field in ("name", "phone", "age_range", "gender", "marital_status"):
            if field in changes and changes[field] is not None:
                setattr(volunteer, field, changes[field])
        if "active" in changes:
            volunteer.active = bool(changes["active"])
        release = bool(args.get("release_request"))
        if volunteer.active is False and volunteer.currently_assigned_request_id:
            release = True
        if release and volunteer.currently_assigned_request_id:
            request = GLOBAL_DB.get_guest_connection_request(volunteer.currently_assigned_request_id)
            if request and request.volunteer_id == volunteer.id:
                request.volunteer_id = None
                if request.status == "MATCHED":
                    request.status = "OPEN"
                GLOBAL_DB.save_guest_connection_request(request)
            volunteer.currently_assigned_request_id = None
        GLOBAL_DB.save_guest_connection_volunteer(volunteer)
        log("guest_volunteer_updated", ctx.correlation_id, ctx.actor_id, ctx.tenant_id, ctx.shard, {"volunteer_id": volunteer.id})
        return VerbResult(ok=True, data=_serialize_guest_volunteer(volunteer))


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
    visitor_id: str | None = None
    guest_name: str | None = None
    contact: str | None = None
    age_range: str | None = None
    gender: str | None = None
    marital_status: str | None = None
    preferred_date: str | None = None
    notes: str | None = None

@register
class GuestRequestCreateVerb(BaseVerb):
    name = "guest_pairing.request_create"
    schema = GuestRequestCreateArgs
    authz_action = None  # allow curious guests to request pairing

    @classmethod
    def execute(cls, args: dict, ctx: VerbContext) -> VerbResult:
        visitor_id = args.get("visitor_id")
        profile: dict | None = None
        if visitor_id and hasattr(GLOBAL_DB, "get_person_profile"):
            profile = GLOBAL_DB.get_person_profile(visitor_id)  # type: ignore[attr-defined]

        def _coalesce(*values: Any, default: Any = None) -> Any:
            for value in values:
                if value not in (None, ""):
                    return value
            return default

        profile_first = profile.get("first_name") if profile else None
        profile_last = profile.get("last_name") if profile else None
        profile_full_name = " ".join([part for part in [profile_first, profile_last] if part]) if (profile_first or profile_last) else None
        guest_name = _coalesce(
            args.get("guest_name"),
            profile_full_name,
            visitor_id,
            default="Guest",
        )

        contact_json = profile.get("contact") if profile else None
        contact_value = _coalesce(
            args.get("contact"),
            (contact_json or {}).get("phone") if isinstance(contact_json, dict) else None,
            (contact_json or {}).get("email") if isinstance(contact_json, dict) else None,
            visitor_id,
            default="unknown",
        )

        age_range = _coalesce(args.get("age_range"), (contact_json or {}).get("age_range") if isinstance(contact_json, dict) else None)
        gender = _coalesce(args.get("gender"), profile.get("gender") if profile else None, default="unknown")
        marital_status = _coalesce(args.get("marital_status"), (contact_json or {}).get("marital_status") if isinstance(contact_json, dict) else None, default="unknown")

        notes_segments: list[str] = []
        if args.get("notes"):
            notes_segments.append(str(args["notes"]))
        if args.get("preferred_date"):
            notes_segments.append(f"Preferred visit date: {args['preferred_date']}")
        household_name = profile.get("household_name") if profile else None
        if household_name:
            notes_segments.append(f"Household: {household_name}")
        notes = " | ".join(notes_segments) if notes_segments else None

        request = GuestConnectionRequest(
            id=new_id(),
            tenant_id=ctx.tenant_id,
            guest_name=guest_name,
            contact=contact_value,
            age_range=age_range or "unspecified",
            gender=gender,
            marital_status=marital_status,
            notes=notes,
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


def _serialize_guest_request(request: GuestConnectionRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "tenant_id": request.tenant_id,
        "guest_name": request.guest_name,
        "contact": request.contact,
        "age_range": request.age_range,
        "gender": request.gender,
        "marital_status": request.marital_status,
        "status": request.status,
        "volunteer_id": request.volunteer_id,
        "notes": request.notes,
        "created_at": request.created_at.isoformat(),
        "updated_at": request.updated_at.isoformat(),
    }


def _serialize_guest_volunteer(volunteer: GuestConnectionVolunteer) -> dict[str, Any]:
    return {
        "id": volunteer.id,
        "tenant_id": volunteer.tenant_id,
        "name": volunteer.name,
        "phone": volunteer.phone,
        "age_range": volunteer.age_range,
        "gender": volunteer.gender,
        "marital_status": volunteer.marital_status,
        "active": volunteer.active,
        "currently_assigned_request_id": volunteer.currently_assigned_request_id,
        "last_matched_at": volunteer.last_matched_at.isoformat() if volunteer.last_matched_at else None,
        "created_at": volunteer.created_at.isoformat(),
        "updated_at": volunteer.updated_at.isoformat(),
    }


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
