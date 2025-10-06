from fastapi.testclient import TestClient
from main import app
from laneA.qa_flow import validate_plan
import pytest

client = TestClient(app)

def test_service_times_next_sunday():
    resp = client.post("/qa", json={"question": "What time are services next Sunday?"}).json()
    assert "services" in resp["answer"].lower()
    assert resp["plan"]["calls"][0]["op"].startswith("service_times.by_date_and_campus")

def test_staff_lookup_pastor():
    resp = client.post("/qa", json={"question": "Who is the pastor?"}).json()
    assert resp["plan"]["calls"][0]["op"] in ("faq.search", "staff.lookup")  # may include faq first
    # ensure if staff.lookup present rows are returned or empty (allowed)

def test_faq_cache_hit():
    q = "Where do I park?"
    first = client.post("/qa", json={"question": q}).json()
    second = client.post("/qa", json={"question": q}).json()
    assert first["cached"] is False
    assert second["cached"] is True
    assert "park" in second["answer"].lower()

def test_unknown_op_rejection():
    with pytest.raises(ValueError):
        validate_plan({"calls": [{"op": "made.up.op", "params": {}}]})
