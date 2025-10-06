from __future__ import annotations
from .repository import GLOBAL_DB


def acquire(shard: str, owner: str, ttl_seconds: int = 30) -> bool:
    return GLOBAL_DB.acquire_shard(shard, owner, ttl_seconds)


def release(shard: str, owner: str):
    GLOBAL_DB.release_shard(shard, owner)
