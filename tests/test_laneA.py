from fastapi.testclient import TestClient
from main import app
from laneA.qa_flow import validate_plan
import pytest

client = TestClient(app)

def test_service_times_next_sunday():
    resp = client.post("/qa", json={"question": "What time are services next Sunday?"}).json()
    assert "services" in resp["answer"].lower()
    assert resp["plan"]["calls"][0]["op"].startswith("service_times.list")

def test_staff_lookup_pastor():
    resp = client.post("/qa", json={"question": "Who is the pastor?"}).json()
    assert resp["plan"]["calls"][0]["op"] in ("faq.search", "staff.lookup")  # may include faq first
    # ensure if staff.lookup present rows are returned or empty (allowed)

def test_middle_school_ministry_plan():
    resp = client.post("/qa", json={"question": "Who is your middle school pastor, and when does middle school ministry meet?"}).json()
    ops = [c["op"] for c in resp["plan"]["calls"]]
    assert "staff.lookup" in ops
    assert "ministry.schedule.by_name" in ops
    answer_lower = resp["answer"].lower()
    assert "middle school" in answer_lower
    assert "pastor jamie" in answer_lower

def test_unknown_op_rejection():
    with pytest.raises(ValueError):
        validate_plan({"calls": [{"op": "made.up.op", "params": {}}]})
