from __future__ import annotations
from collections import defaultdict

_COUNTERS = defaultdict(int)


def inc(name: str, value: int = 1):
    _COUNTERS[name] += value


def snapshot():
    return dict(_COUNTERS)
