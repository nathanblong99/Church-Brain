from __future__ import annotations
from typing import List, Dict, Any
from datetime import datetime, timedelta
import difflib

ALLOWED_OPS: dict[str, list[str]] = {
    "service_times.list": ["campus", "campus_id", "date", "start_date", "end_date", "limit"],
    "staff.lookup": ["role", "campus"],
    "parking.by_campus": ["campus"],
    "childcare.policy.by_service": ["service_time", "date"],
    "events.upcoming.by_campus": ["campus", "limit"],
    "faq.search": ["query"],
    "ministry.schedule.by_name": ["name"],
}

_NOW = datetime.utcnow

# In-memory sample dataset (Phase 2 demo; replace with adapters later)
DATA = {
    "campus": [
        {"id": "c1", "name": "Main", "address": "123 Hope Rd", "parking_notes": "Use west lot; overflow east."},
        {"id": "c2", "name": "North", "address": "77 North Ave", "parking_notes": "Limited street parking."},
    ],
    "service": [],
    "staff": [
        {"id": "s1", "name": "Pastor Amy", "role": "pastor", "campus_id": "c1"},
        {"id": "s2", "name": "Logan", "role": "staff", "campus_id": "c1"},
        {"id": "s3", "name": "Riley", "role": "intern", "campus_id": "c1"},
        {"id": "s4", "name": "Jordan", "role": "volunteer_coordinator", "campus_id": "c2"},
    ],
    "event": [],
    "faq": [
        {"id": "f1", "question": "What time are Sunday services?", "answer": "Services are at 9:00 and 11:00 AM at the Main campus.", "tags": ["service_times"]},
        {"id": "f2", "question": "Is childcare available?", "answer": "Childcare is offered during all morning services.", "tags": ["childcare"]},
        {"id": "f3", "question": "Where do I park?", "answer": "Park in the west lot; overflow is in the east lot.", "tags": ["parking"]},
    ],
    "ministry": [
        {
            "id": "ministry_middle_school",
            "name": "middle school",
            "meeting_day": "Wednesday",
            "meeting_time": "18:30",
            "location": "Student Center",
            "notes": "Weekly gathering with worship and small groups.",
        }
    ],
}

# Populate sample upcoming services (today + next Sunday)
def _init_services():
    today = _NOW().date()
    # find next Sunday
    days_ahead = (6 - today.weekday()) % 7  # 6=Sunday if Monday=0
    next_sunday = today + timedelta(days=days_ahead or 7)
    for service_time in ["09:00", "11:00"]:
        DATA["service"].append({
            "id": f"svc-{next_sunday}-{service_time}",
            "campus_id": "c1",
            "date": str(next_sunday),
            "time": service_time,
            "childcare_available": True,
        })

_init_services()

# Attempt to merge dev seed data if present (non-destructive)
try:  # avoid circular imports if imported early
    from state.repository import GLOBAL_DB  # type: ignore
    # Campuses
    if hasattr(GLOBAL_DB, "campuses"):
        existing_ids = {c["id"] for c in DATA["campus"]}
        for c in getattr(GLOBAL_DB, "campuses"):
            if c["id"] not in existing_ids:
                DATA["campus"].append({
                    "id": c["id"],
                    "name": c.get("name", c["id"]),
                    "address": c.get("address", ""),
                    "parking_notes": c.get("parking_notes", "")
                })
    # Services
    if hasattr(GLOBAL_DB, "services"):
        svc_ids = {s["id"] for s in DATA["service"]}
        for s in getattr(GLOBAL_DB, "services"):
            if s["id"] not in svc_ids:
                DATA["service"].append({
                    "id": s["id"],
                    "campus_id": s["campus_id"],
                    "date": s["date"],
                    "time": s["time"],
                    "childcare_available": s.get("childcare_available", False)
                })
    # Staff
    if hasattr(GLOBAL_DB, "staff_directory"):
        staff_ids = {s["id"] for s in DATA["staff"]}
        for s in getattr(GLOBAL_DB, "staff_directory"):
            if s["id"] not in staff_ids:
                DATA["staff"].append(s)
    # Events
    if hasattr(GLOBAL_DB, "events"):
        event_ids = {e["id"] for e in DATA["event"]}
        for e in getattr(GLOBAL_DB, "events"):
            if e["id"] not in event_ids:
                DATA["event"].append(e)
    # FAQs
    if hasattr(GLOBAL_DB, "faqs_full"):
        faq_ids = {f["id"] for f in DATA.get("faq", [])}
        for f in getattr(GLOBAL_DB, "faqs_full"):
            if f["id"] not in faq_ids:
                DATA["faq"].append(f)
    # Ministry schedules
    if hasattr(GLOBAL_DB, "ministry_schedules"):
        ministry_ids = {m["id"] for m in DATA.get("ministry", [])}
        for m in getattr(GLOBAL_DB, "ministry_schedules"):
            if m["id"] not in ministry_ids:
                DATA["ministry"].append(m)
except Exception:
    pass

def _campus_name(campus_id: str) -> str:
    for c in DATA["campus"]:
        if c["id"] == campus_id:
            return c["name"]
    return campus_id

def _campus_meta(campus_id: str) -> dict[str, Any]:
    for c in DATA["campus"]:
        if c["id"] == campus_id:
            return c
    return {"id": campus_id, "name": campus_id}

def _resolve_campus_id(name_or_id: str | None) -> str | None:
    if not name_or_id:
        return None
    for c in DATA["campus"]:
        if c["id"].lower() == name_or_id.lower() or c["name"].lower() == name_or_id.lower():
            return c["id"]
    return None

def _service_times_rows(params: Dict[str, Any]) -> list[dict[str, Any]]:
    date = params.get("date")
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    campus = params.get("campus")
    campus_id_param = params.get("campus_id")
    limit = params.get("limit")
    if date == "next_sunday":
        today = _NOW().date()
        days_ahead = (6 - today.weekday()) % 7
        target = today + timedelta(days=days_ahead or 7)
        date = str(target)
    resolved_campus_id = _resolve_campus_id(campus_id_param or campus)
    rows: list[dict[str, Any]] = []
    for svc in sorted(DATA["service"], key=lambda s: (s["date"], s["time"])):
        if date and svc["date"] != date:
            continue
        if start_date and svc["date"] < start_date:
            continue
        if end_date and svc["date"] > end_date:
            continue
        if resolved_campus_id and svc["campus_id"] != resolved_campus_id:
            continue
        meta = _campus_meta(svc["campus_id"])
        rows.append({
            "service_id": svc["id"],
            "date": svc["date"],
            "time": svc["time"],
            "campus_id": svc["campus_id"],
            "campus_name": meta.get("name", svc["campus_id"]),
            "campus_address": meta.get("address"),
            "parking_notes": meta.get("parking_notes"),
            "childcare_available": svc.get("childcare_available", False),
        })
    if limit:
        try:
            lim = max(1, int(limit))
            rows = rows[:lim]
        except (TypeError, ValueError):
            pass
    return rows


def run_catalog_op(op: str, params: Dict[str, Any]) -> Dict[str, Any]:
    normalized_op = op
    if op not in ALLOWED_OPS:
        # Legacy compatibility
        if op == "service_times.by_date_and_campus":
            normalized_op = "service_times.list"
            allowed = ["date", "campus"]
        else:
            return {"error": "unknown_op"}
    else:
        allowed = ALLOWED_OPS[normalized_op]
    # discard unexpected params
    clean = {k: v for k, v in params.items() if k in allowed and v is not None}

    # Helpers to combine baked-in + seeded data (avoids stale snapshots)
    staff_records = list(DATA.get("staff", []))
    if hasattr(GLOBAL_DB, "staff_directory"):
        for s in getattr(GLOBAL_DB, "staff_directory"):
            if not any(existing["id"] == s["id"] for existing in staff_records):
                staff_records.append(s)

    ministry_records = list(DATA.get("ministry", []))
    if hasattr(GLOBAL_DB, "ministry_schedules"):
        for m in getattr(GLOBAL_DB, "ministry_schedules"):
            if not any(existing["id"] == m["id"] for existing in ministry_records):
                ministry_records.append(m)

    if normalized_op == "service_times.list":
        rows = _service_times_rows(clean)
        return {"op": op, "params": clean, "rows": rows}

    if normalized_op == "staff.lookup":
        role = clean.get("role")
        campus = clean.get("campus")
        campus_id = _resolve_campus_id(campus) if campus else None
        rows = []
        for s in staff_records:
            if role and s["role"] != role:
                continue
            if campus_id and s.get("campus_id") != campus_id:
                continue
            rows.append({
                "id": s["id"],
                "name": s["name"],
                "role": s["role"],
                "campus_name": _campus_name(s.get("campus_id") or "") if s.get("campus_id") else None,
            })
        return {"op": op, "params": clean, "rows": rows}

    if normalized_op == "parking.by_campus":
        campus = clean.get("campus")
        campus_id = _resolve_campus_id(campus) if campus else None
        rows = []
        for c in DATA["campus"]:
            if campus_id and c["id"] != campus_id:
                continue
            rows.append({"campus_name": c["name"], "parking_notes": c.get("parking_notes")})
        return {"op": op, "params": clean, "rows": rows}

    if op == "childcare.policy.by_service":
        # Accept either date or service_time (HH:MM) + optional date
        svc_time = clean.get("service_time")
        date = clean.get("date")
        rows = []
        for svc in DATA["service"]:
            if date and svc["date"] != date:
                continue
            if svc_time and svc["time"] != svc_time:
                continue
            rows.append({
                "date": svc["date"],
                "time": svc["time"],
                "campus_name": _campus_name(svc["campus_id"]),
                "childcare_available": svc["childcare_available"],
            })
        return {"op": op, "params": clean, "rows": rows}

    if op == "events.upcoming.by_campus":
        campus = clean.get("campus")
        limit = int(clean.get("limit", 5) or 5)
        campus_id = _resolve_campus_id(campus) if campus else None
        # For now events dataset empty; return [] placeholder
        rows: list[dict[str, Any]] = []
        return {"op": op, "params": clean, "rows": rows[:limit]}

    if op == "faq.search":
        query = (clean.get("query") or "").lower()
        rows = []
        if not query:
            return {"op": op, "params": clean, "rows": []}
        for f in DATA["faq"]:
            hay = f["question"].lower() + " " + f["answer"].lower()
            if query in hay:
                rows.append({"id": f["id"], "question": f["question"], "answer": f["answer"]})
        # simple fuzzy fallback if no direct contains
        if not rows:
            questions = [f["question"] for f in DATA["faq"]]
            close = difflib.get_close_matches(query, questions, n=2, cutoff=0.6)
            for f in DATA["faq"]:
                if f["question"] in close:
                    rows.append({"id": f["id"], "question": f["question"], "answer": f["answer"]})
        return {"op": op, "params": clean, "rows": rows}

    if op == "ministry.schedule.by_name":
        name = (clean.get("name") or "").lower()
        rows = []
        for m in ministry_records:
            if not name or name in m.get("name", "").lower():
                rows.append({
                    "id": m["id"],
                    "name": m["name"],
                    "meeting_day": m.get("meeting_day"),
                    "meeting_time": m.get("meeting_time"),
                    "location": m.get("location"),
                    "notes": m.get("notes"),
                })
        return {"op": op, "params": clean, "rows": rows}

    return {"op": op, "params": clean, "rows": []}
