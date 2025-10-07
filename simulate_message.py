#!/usr/bin/env python3
"""Simulate an inbound message and show system logs"""
import sys
import json
sys.path.insert(0, 'src')

# Clear event log
from state import repository
repository.EVENTS = []

from laneA.qa_flow import answer_question
from router.llm_router import route_with_plan
from router.classifier import derive_event_key
from state.event_log import log
import uuid

# Simulate the inbound message
message_text = "What are your service times and what is your head pastor's name"
tenant_id = "Main"
actor_id = "guest_001"
actor_roles = ["guest"]
channel = "sms"

print("=" * 60)
print("INCOMING MESSAGE")
print("=" * 60)
print(f"From: {actor_id} (roles: {actor_roles})")
print(f"Tenant: {tenant_id}")
print(f"Channel: {channel}")
print(f"Message: \"{message_text}\"")
print()

# Classify the message via LLM router
routing = route_with_plan(
    message_text,
    tenant_id=tenant_id,
    actor_id=actor_id,
    actor_roles=actor_roles,
    include_plan=True,
)
lane = routing["lane"]
event_key = derive_event_key(message_text)
correlation_id = uuid.uuid4().hex

print("=" * 60)
print("ROUTING DECISION")
print("=" * 60)
print(f"Lane: {lane}")
print(f"Event Key: {event_key}")
print(f"Correlation ID: {correlation_id}")
print()

# Process based on lane (this is what /ingest does)
if lane == "A" or lane == "HYBRID":
    print("=" * 60)
    print("LANE A PROCESSING (Q&A)")
    print("=" * 60)
    qa_result = answer_question(message_text, precomputed_plan=routing.get("qa_plan"))
    log("ingest_laneA", correlation_id, actor_id, tenant_id, None, {"calls": qa_result.get("plan", {}).get("calls", [])})

    print(f"Cached: {qa_result.get('cached', False)}")
    print(f"Plan calls: {len(qa_result.get('plan', {}).get('calls', []))}")
    print(f"\nAnswer to user:")
    print(f"  \"{qa_result.get('answer', 'N/A')}\"")
    print()

# Show the background system logs
print("=" * 60)
print("SYSTEM BACKGROUND LOGS")
print("=" * 60)
print("(These are logged to event_log and would go to observability)")
print()

events = repository.EVENTS
for i, event in enumerate(events, 1):
    print(f"[Log Entry {i}]")
    print(f"  Event Type: {event.kind}")
    print(f"  Timestamp: {event.timestamp.isoformat()}")
    print(f"  Correlation ID: {event.correlation_id}")
    print(f"  Actor: {event.actor}")
    print(f"  Tenant: {event.tenant_id}")
    if event.shard:
        print(f"  Shard: {event.shard}")
    print(f"  Data: {json.dumps(event.data, indent=4)}")
    print()
