from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import re
from datetime import datetime

Lane = Literal["A", "B", "HYBRID"]

# Heuristic patterns
_INFO_PAT = re.compile(r"\b(when|where|what time|who|parking|child ?care|faq|schedule|event|service)\b", re.IGNORECASE)
_ACTION_PAT = re.compile(r"\b(invite|assign|book|rent|reserve|send|text|email|notify|create|update|adjust|hold|confirm|cancel)\b", re.IGNORECASE)
_MIX_PAT = re.compile(r"\b(invite|book|rent).*(when|what time|where)| (when|what time).*(invite|book|rent)\b", re.IGNORECASE)
_EVENT_KEY_TOPIC_PAT = re.compile(r"\b(catalyst|retreat|camp|outreach)\b", re.IGNORECASE)

@dataclass
class RouteResult:
    lane: Lane
    eventKey: str
    tenantId: str
    actor: str
    channel: str
    correlationId: str


def classify(text: str) -> Lane:
    t = text.lower()
    # Hybrid if both strong info and action cues
    if _MIX_PAT.search(t) or (_INFO_PAT.search(t) and _ACTION_PAT.search(t)):
        return "HYBRID"
    if _ACTION_PAT.search(t):
        return "B"
    return "A"


def derive_event_key(text: str) -> str:
    # Find known topic else General
    topic_match = _EVENT_KEY_TOPIC_PAT.search(text)
    topic = topic_match.group(1).title() if topic_match else "General"
    date = datetime.utcnow().date().isoformat()
    # Default campus placeholder Main (future: parse campus)
    return f"{topic}@{date}@Main"
