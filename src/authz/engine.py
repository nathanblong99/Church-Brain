from __future__ import annotations
from typing import Dict, Any, Tuple

# Simple static role policy map for Phase 1
# action -> required role(s)
POLICY = {
    "volunteer.manage": ["pastor", "staff"],
    "room.allocate": ["pastor", "staff"],
    "message.send": ["pastor", "staff", "intern"],
    "planning.create": ["pastor", "staff", "intern"],
}


def can(actor_roles: list[str], action: str, resource: str | None = None, ctx: Dict[str, Any] | None = None) -> Tuple[bool, str]:
    required = POLICY.get(action)
    if not required:
        return False, f"default_deny: action {action} not in policy"
    if any(r in actor_roles for r in required):
        return True, "allow"
    return False, f"missing_role: need one of {required}"
