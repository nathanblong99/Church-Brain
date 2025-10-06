from __future__ import annotations
"""
Deterministic post-execution detectors for Lane B.
Given the execution results (ordered list of {verb, data}) and the plan json, emit
structured signals describing notable states that could merit a clarifying question.

We keep this pure / side-effect free so it can be unit tested and remains stable.
"""
from typing import List, Dict, Any, Optional

Signal = Dict[str, Any]


def detect_signals(plan: Dict[str, Any], results: List[Dict[str, Any]]) -> List[Signal]:
    signals: List[Signal] = []
    # Volunteer request creation / update introspection
    created_request_id: Optional[str] = None
    for step, res in zip(plan.get("steps", []), results):
        verb = step.get("verb")
        if verb == "create_record" and res.get("data", {}).get("id"):
            created_request_id = res["data"]["id"]
            # record basic signal so summary can mention it
            signals.append({
                "type": "volunteer_request_created",
                "request_id": created_request_id,
                "basketball_needed": step.get("args", {}).get("data", {}).get("basketball_needed"),
                "volleyball_needed": step.get("args", {}).get("data", {}).get("volleyball_needed"),
            })
        if verb == "update_record" and step.get("args", {}).get("kind") == "volunteer_request":
            signals.append({
                "type": "volunteer_request_updated",
                "request_id": step.get("args", {}).get("id"),
                "basketball_needed": step.get("args", {}).get("data", {}).get("basketball_needed"),
                "volleyball_needed": step.get("args", {}).get("data", {}).get("volleyball_needed"),
            })

    # Room hold signals (success/failure) placeholder — results contain data or error already handled upstream.
    for step, res in zip(plan.get("steps", []), results):
        verb = step.get("verb")
        if verb == "room.hold":
            if res.get("data"):
                signals.append({"type": "room_hold_created", "room_id": step.get("args", {}).get("room_id")})
            else:
                signals.append({"type": "room_hold_failed", "room_id": step.get("args", {}).get("room_id")})

    return signals


def choose_clarifying_question(signals: List[Signal]) -> Optional[Dict[str, Any]]:
    """Pick a single clarifying question descriptor deterministically.
    We map certain signal combinations to a question code + params. LLM later phrases it.
    Returns None if no question warranted.
    """
    # Priority ordering
    for s in signals:
        if s["type"] == "volunteer_request_created":
            # Ask if we should start inviting volunteers now.
            needed = (s.get("basketball_needed") or 0) + (s.get("volleyball_needed") or 0)
            if needed > 0:
                return {"code": "invite_next", "request_id": s["request_id"], "needed": needed}
        if s["type"] == "volunteer_request_updated":
            needed = (s.get("basketball_needed") or 0) + (s.get("volleyball_needed") or 0)
            if needed > 0:
                return {"code": "adjust_follow_up", "request_id": s["request_id"], "needed": needed}
    # Room failure placeholder
    for s in signals:
        if s["type"] == "room_hold_failed":
            return {"code": "room_alternative", "room_id": s.get("room_id")}
    return None
