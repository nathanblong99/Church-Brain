from __future__ import annotations
from typing import Any, Dict
from datetime import datetime
import json


def structured_log(event: str, correlation_id: str, data: Dict[str, Any]):
    record = {
        "ts": datetime.utcnow().isoformat(),
        "event": event,
        "cid": correlation_id,
        "data": data,
    }
    print(json.dumps(record))
