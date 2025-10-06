from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional, Tuple
from state.repository import GLOBAL_DB
from state.models import RoomHold, new_id, VolunteerRequest

HOLD_TTL_SECONDS = 120


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def room_hold(tenant_id: str, room_id: str, start: datetime, end: datetime) -> Tuple[bool, Optional[RoomHold], str]:
    # check overlaps with confirmed holds
    active = GLOBAL_DB.get_active_room_holds(tenant_id, room_id)
    for h in active:
        if h.status == "CONFIRMED" and _overlaps(start, end, h.start, h.end):
            return False, None, "conflict_confirmed"
    # create hold
    hold = RoomHold(
        id=new_id(),
        tenant_id=tenant_id,
        room_id=room_id,
        start=start,
        end=end,
        status="HOLD",
        expires_at=datetime.utcnow() + timedelta(seconds=HOLD_TTL_SECONDS),
    )
    GLOBAL_DB.save_room_hold(hold)
    return True, hold, "ok"


def room_confirm(hold_id: str) -> Tuple[bool, str]:
    hold = GLOBAL_DB.room_holds.get(hold_id)
    if not hold:
        return False, "not_found"
    if hold.is_expired():
        hold.status = "CANCELED"
        GLOBAL_DB.save_room_hold(hold)
        return False, "expired"
    # ensure no newly confirmed conflicting reservations since hold creation
    active = GLOBAL_DB.get_active_room_holds(hold.tenant_id, hold.room_id)
    for h in active:
        if h.id != hold.id and h.status == "CONFIRMED" and _overlaps(hold.start, hold.end, h.start, h.end):
            return False, "race_conflict"
    hold.status = "CONFIRMED"
    GLOBAL_DB.save_room_hold(hold)
    return True, "ok"


def adjust_hold(hold_id: str, new_start: datetime, new_end: datetime) -> Tuple[bool, str]:
    hold = GLOBAL_DB.room_holds.get(hold_id)
    if not hold:
        return False, "not_found"
    if hold.status not in ("HOLD", "CONFIRMED"):
        return False, "invalid_state"
    # check conflicts (exclude self)
    for h in GLOBAL_DB.get_active_room_holds(hold.tenant_id, hold.room_id):
        if h.id == hold.id:
            continue
        if h.status == "CONFIRMED" and _overlaps(new_start, new_end, h.start, h.end):
            return False, "conflict_confirmed"
    hold.start = new_start
    hold.end = new_end
    GLOBAL_DB.save_room_hold(hold)
    return True, "ok"

# Volunteer overlap check placeholder

def volunteer_role_counts(req: VolunteerRequest) -> dict:
    return {role: len(ids) for role, ids in req.assignments.items()}
