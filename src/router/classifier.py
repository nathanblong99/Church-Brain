from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import re
from datetime import datetime

Lane = Literal["A", "B", "HYBRID"]

_EVENT_KEY_TOPIC_PAT = re.compile(r"\b(catalyst|retreat|camp|outreach)\b", re.IGNORECASE)


def derive_event_key(text: str) -> str:
    # Find known topic else General
    topic_match = _EVENT_KEY_TOPIC_PAT.search(text)
    topic = topic_match.group(1).title() if topic_match else "General"
    date = datetime.utcnow().date().isoformat()
    # Default campus placeholder Main (future: parse campus)
    return f"{topic}@{date}@Main"
