from __future__ import annotations
from datetime import datetime, timedelta, date, time
import os
from hashlib import sha256
from state.repository import GLOBAL_DB
from state.models import VolunteerRequest, RoomHold


ANCHOR_ENV_VAR = "CHURCH_BRAIN_ANCHOR_DATE"  # YYYY-MM-DD
SCALE_ENV_VAR = "CHURCH_BRAIN_SEED_SCALE"    # Int multiplier (default 1)

def _anchor_date() -> date:
    val = os.getenv(ANCHOR_ENV_VAR, "2025-01-05")  # pick a fixed Sunday
    return datetime.strptime(val, "%Y-%m-%d").date()

def _dt(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(hour=h, minute=m))

def _scale() -> int:
    try:
        return max(1, int(os.getenv(SCALE_ENV_VAR, "1")))
    except ValueError:
        return 1

def reset_db_state():
    """Clear dynamic collections for reproducible reseed (tests)."""
    GLOBAL_DB.event_log.clear()
    GLOBAL_DB.volunteer_requests.clear()
    GLOBAL_DB.room_holds.clear()
    # do not clear idempotency/outbox by default (could be optional) but for reproducibility we will:
    GLOBAL_DB.outbox.clear()
    GLOBAL_DB.idempotency.clear()
    GLOBAL_DB.shard_locks.clear()
    if hasattr(GLOBAL_DB, "_mega_seed_loaded"):
        delattr(GLOBAL_DB, "_mega_seed_loaded")

def load_dev_seed():
    """Load deterministic mega-church seed.

    Determinism principles:
    - All dates anchored to ANCHOR_DATE + fixed offsets (no utcnow randomness)
    - No random module usage
    - Stable IDs (predictable) for events/services/holds/volunteer requests
    - Reseeding idempotent (second call no-ops)
    """
    if getattr(GLOBAL_DB, "_mega_seed_loaded", False):
        return

    anchor = _anchor_date()  # e.g., 2025-01-05 (a Sunday)

    # Campuses (static)
    campuses = [
        {"id": "c_main", "name": "Main", "address": "100 Hope Blvd", "parking_notes": "West + overflow East"},
        {"id": "c_north", "name": "North", "address": "555 North Pkwy", "parking_notes": "Shared lot; arrive early"},
        {"id": "c_south", "name": "South", "address": "88 South Ave", "parking_notes": "Street + garage level 2"},
    ]
    GLOBAL_DB.campuses = campuses  # type: ignore

    # Staff: deterministic assignment (cycle roles & campuses) with scale
    base_roles = [
        "pastor","staff","intern","volunteer_coordinator","media","worship","kids","outreach",
        "security","care","facilities","technical","production","hospitality","parking","followup"
    ]
    roles = base_roles
    staff = []
    role_count = len(roles)
    campus_ids = [c["id"] for c in campuses]
    campus_count = len(campus_ids)
    scale = _scale()
    staff_total = 120 * scale + (380 if scale > 1 else 0)  # ~500 when scale=2
    for i in range(1, staff_total + 1):
        role = roles[(i - 1) % role_count]
        # every 7th is multi-campus (None), else round-robin campus
        campus_id = None if i % 7 == 0 else campus_ids[(i - 1) % campus_count]
        staff.append({
            "id": f"staff_{i:04d}",
            "name": f"Person {i:04d}",
            "role": role,
            "campus_id": campus_id
        })
    GLOBAL_DB.staff_directory = staff  # type: ignore

    # Services: 12 * scale Sundays at 09:00 & 11:00 (+ 17:00 evening every 2nd week for Main)
    services = []
    service_weeks = 12 * scale
    for week in range(service_weeks):
        sunday = anchor + timedelta(weeks=week)
        for campus in campuses:
            for time_str in ["09:00", "11:00"]:
                childcare = True if time_str == "09:00" else (week % 2 == 0)
                services.append({
                    "id": f"svc_{campus['id']}_{sunday}_{time_str}",
                    "campus_id": campus["id"],
                    "date": str(sunday),
                    "time": time_str,
                    "childcare_available": childcare
                })
        # Evening service only at Main every even week
        if week % 2 == 0:
            services.append({
                "id": f"svc_c_main_{sunday}_17:00",
                "campus_id": "c_main",
                "date": str(sunday),
                "time": "17:00",
                "childcare_available": False
            })
    GLOBAL_DB.services = services  # type: ignore

    # Events: deterministic generation. Target ~100 when scale=1.
    event_names = [
        "Youth Night","Prayer Gathering","Leadership Huddle","Community Meal","Choir Practice",
        "Baptism Class","Volunteer Rally","Men's Breakfast","Women's Brunch","Family Movie Night"
    ]
    events = []
    eid = 1
    event_weeks = 12 * scale
    for week in range(event_weeks):
        base_monday = anchor + timedelta(weeks=week) + timedelta(days=1)  # Monday
        # schedule Tue(18), Thu(18), Sat(09) for each campus
        for offset, hour in [(1,18),(3,18),(5,9)]:
            day = base_monday + timedelta(days=offset)
            for campus in campuses:
                name = event_names[(eid - 1) % len(event_names)]
                start = _dt(day, hour)
                duration = 2 if hour >= 18 else 3
                end = start + timedelta(hours=duration)
                events.append({
                    "id": f"evt_{eid:04d}",
                    "name": name,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "campus_id": campus["id"]
                })
                eid += 1
                if eid > 100 * scale:  # cap
                    break
            if eid > 100 * scale:
                break
        if eid > 100 * scale:
            break
    GLOBAL_DB.events = events  # type: ignore

    # FAQs (static)
    GLOBAL_DB.faqs_full = [  # type: ignore
        {"id": "f_time", "question": "What time are Sunday services?", "answer": "Services at Main, North, South: 9:00 & 11:00 AM.", "tags": ["service_times"]},
        {"id": "f_childcare", "question": "Is childcare available?", "answer": "Childcare during 9:00 at all campuses; 11:00 varies.", "tags": ["childcare"]},
        {"id": "f_parking", "question": "Where do I park?", "answer": "Main: West lot. North: Shared front. South: Garage Level 2.", "tags": ["parking"]},
        {"id": "f_address", "question": "What are campus addresses?", "answer": "See campuses page: Main 100 Hope Blvd; North 555 North Pkwy; South 88 South Ave.", "tags": ["campus"]},
        {"id": "f_contact", "question": "How do I contact a pastor?", "answer": "Email office@church.example and we'll route appropriately.", "tags": ["contact"]},
        {"id": "f_vision", "question": "What is the church vision?", "answer": "To serve the city with hope and practical love.", "tags": ["vision"]},
        {"id": "f_giving", "question": "How can I give?", "answer": "Online portal or drop boxes in the lobby.", "tags": ["giving"]},
        {"id": "f_groups", "question": "How do I join a small group?", "answer": "Visit the groups page or ask the welcome desk.", "tags": ["groups"]},
        {"id": "f_baptism", "question": "How do I get baptized?", "answer": "Attend the Baptism Class listed on the events page.", "tags": ["baptism"]},
        {"id": "f_membership", "question": "How do I become a member?", "answer": "Complete membership class; schedule quarterly.", "tags": ["membership"]},
        {"id": "f_kids_checkin", "question": "Where do I check in kids?", "answer": "Kids wing entrance near the south lobby.", "tags": ["kids"]},
        {"id": "f_students", "question": "When do students meet?", "answer": "Wednesday nights at 6:30 PM.", "tags": ["students"]},
        {"id": "f_coffee", "question": "Do you serve coffee?", "answer": "Yes, free drip and a low-cost espresso bar.", "tags": ["amenities"]},
        {"id": "f_accessibility", "question": "Is there accessible seating?", "answer": "Accessible seating is reserved front-left of the auditorium.", "tags": ["accessibility"]},
        {"id": "f_translation", "question": "Is translation available?", "answer": "Spanish translation at 11:00 Main campus.", "tags": ["translation"]},
        {"id": "f_music_style", "question": "What is the worship style?", "answer": "Modern contemporary with occasional hymns.", "tags": ["worship"]},
        {"id": "f_length", "question": "How long are services?", "answer": "About 75 minutes.", "tags": ["service_length"]},
        {"id": "f_communion", "question": "How often is communion?", "answer": "First Sunday of each month.", "tags": ["communion"]},
    ]

    # Volunteer Requests: base fixed + generated to reach ~30 when scale=1
    fixed_requests = [
        ("vr_static_1", 4, 6),
        ("vr_static_2", 2, 3),
        ("vr_static_3", 8, 2),  # will be over-assigned to test rebalance logic later
        ("vr_static_4", 5, 5),
        ("vr_static_5", 6, 7),
    ]
    for rid, b_need, v_need in fixed_requests:
        vr = VolunteerRequest(
            id=rid,
            tenant_id="tenant_dev",
            basketball_needed=b_need,
            volleyball_needed=v_need,
        )
        GLOBAL_DB.save_volunteer_request(vr)

    # Generated additional requests
    target_requests = 30 * scale
    current = len(fixed_requests)
    idx = 1
    while current < target_requests:
        rid = f"vr_auto_{idx:03d}"
        b_need = 2 + (idx % 7)  # 2..8
        v_need = 2 + ((idx * 3) % 6)  # 2..7
        vr = VolunteerRequest(
            id=rid,
            tenant_id="tenant_dev",
            basketball_needed=b_need,
            volleyball_needed=v_need,
        )
        # partial assignments for variety (use first staff IDs)
        if idx % 4 == 0:  # add some assigned already
            assigned_b = min( max(0, b_need - 1), 3)
            assigned_v = min( max(0, v_need - 2), 3)
            vr.assignments["basketball"] = [f"staff_{i:04d}" for i in range(1, assigned_b + 1)]
            vr.assignments["volleyball"] = [f"staff_{i:04d}" for i in range(assigned_b + 1, assigned_b + 1 + assigned_v)]
        GLOBAL_DB.save_volunteer_request(vr)
        current += 1
        idx += 1

    # Over-assign one request deliberately to test balancing scenarios
    over = GLOBAL_DB.volunteer_requests.get("vr_static_3")
    if over:
        over.assignments["basketball"] = [f"staff_{i:04d}" for i in range(1, over.basketball_needed + 2)]  # +1 over target
        GLOBAL_DB.save_volunteer_request(over)

    # Rooms metadata + deterministic holds (expanded)
    GLOBAL_DB.rooms_meta = [  # type: ignore
        {"id": "gym", "name": "Gym", "capacity": 400},
        {"id": "chapel", "name": "Chapel", "capacity": 180},
        {"id": "auditorium", "name": "Auditorium", "capacity": 1500},
        {"id": "kids_a", "name": "Kids A", "capacity": 40},
        {"id": "kids_b", "name": "Kids B", "capacity": 40},
        {"id": "studio", "name": "Studio", "capacity": 25},
        {"id": "conference_a", "name": "Conference A", "capacity": 30},
        {"id": "cafe", "name": "Cafe", "capacity": 120},
    ]
    # Confirmed holds
    hold1 = RoomHold(id="hold_gym_1", tenant_id="tenant_dev", room_id="gym", start=_dt(anchor + timedelta(days=1), 17), end=_dt(anchor + timedelta(days=1), 20), status="CONFIRMED", expires_at=_dt(anchor + timedelta(days=1), 12))
    hold2 = RoomHold(id="hold_chapel_1", tenant_id="tenant_dev", room_id="chapel", start=_dt(anchor + timedelta(days=2), 18), end=_dt(anchor + timedelta(days=2), 21), status="CONFIRMED", expires_at=_dt(anchor + timedelta(days=2), 12))
    GLOBAL_DB.save_room_hold(hold1)
    GLOBAL_DB.save_room_hold(hold2)
    # Active HOLDs (long expiry so not expired even if anchor is past current date)
    active_hold = RoomHold(id="hold_gym_overlap_hold_1", tenant_id="tenant_dev", room_id="gym", start=_dt(anchor + timedelta(days=1), 18), end=_dt(anchor + timedelta(days=1), 21), status="HOLD", expires_at=_dt(anchor + timedelta(days=365), 12))
    GLOBAL_DB.save_room_hold(active_hold)
    # Additional holds series for scale testing
    for idx_h in range(3, 3 + (5 * scale)):
        # rotate rooms
        room = GLOBAL_DB.rooms_meta[idx_h % len(GLOBAL_DB.rooms_meta)]["id"]
        start = _dt(anchor + timedelta(days=7 + idx_h), 16)
        rh = RoomHold(
            id=f"hold_{room}_{idx_h}",
            tenant_id="tenant_dev",
            room_id=room,
            start=start,
            end=start + timedelta(hours=2 + (idx_h % 3)),
            status="HOLD" if idx_h % 2 == 0 else "CONFIRMED",
            expires_at=start + timedelta(hours=1)
        )
        GLOBAL_DB.save_room_hold(rh)

    GLOBAL_DB._mega_seed_loaded = True

def snapshot_hash() -> str:
    """Produce a stable hash of seeded state for reproducibility tests."""
    import json
    payload = {
        "campuses": getattr(GLOBAL_DB, "campuses", []),
        "staff": getattr(GLOBAL_DB, "staff_directory", []),
        "services": getattr(GLOBAL_DB, "services", []),
        "events": getattr(GLOBAL_DB, "events", []),
        "faqs": getattr(GLOBAL_DB, "faqs_full", []),
        "volunteer_requests": [vr.__dict__ for vr in GLOBAL_DB.volunteer_requests.values()],
        "room_holds": [rh.__dict__ for rh in GLOBAL_DB.room_holds.values()],
        "rooms_meta": getattr(GLOBAL_DB, "rooms_meta", []),
        "scale": _scale(),
    }
    # Sort for deterministic ordering
    def _sort(obj):
        if isinstance(obj, list):
            return sorted((_sort(o) for o in obj), key=lambda x: str(x))
        if isinstance(obj, dict):
            return {k: _sort(obj[k]) for k in sorted(obj.keys())}
        return obj
    normalized = _sort(payload)
    ser = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    return sha256(ser.encode()).hexdigest()
