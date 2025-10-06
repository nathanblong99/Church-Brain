from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_route_lane_a():
    r = client.post('/route', json={
        'tenant_id': 't1', 'actor_id': 'u1', 'actor_roles': ['intern'], 'channel': 'cli', 'text': 'When are services?'
    }).json()
    assert r['lane'] == 'A'

def test_route_lane_b():
    r = client.post('/route', json={
        'tenant_id': 't1', 'actor_id': 'u1', 'actor_roles': ['intern'], 'channel': 'cli', 'text': 'Invite 4 volunteers'
    }).json()
    assert r['lane'] == 'B'

def test_route_hybrid():
    r = client.post('/route', json={
        'tenant_id': 't1', 'actor_id': 'u1', 'actor_roles': ['intern'], 'channel': 'cli', 'text': 'Invite 2 volunteers and when are services?'
    }).json()
    assert r['lane'] == 'HYBRID'

def test_ingest_lane_a():
    r = client.post('/ingest', json={
        'tenant_id': 't1', 'actor_id': 'u1', 'actor_roles': ['intern'], 'channel': 'cli', 'text': 'Where do I park?'
    }).json()
    assert r['lane'] == 'A'
    assert 'park' in r['answer'].lower()

def test_ingest_lane_b_plan_only():
    r = client.post('/ingest', json={
        'tenant_id': 't1', 'actor_id': 'u1', 'actor_roles': ['intern'], 'channel': 'cli', 'text': 'Invite 2 volunteers (1 basketball, 1 volleyball)'
    }).json()
    assert r['lane'] == 'B'
    assert r['plan'] is not None
    assert r.get('answer') is None

def test_ingest_hybrid():
    r = client.post('/ingest', json={
        'tenant_id': 't1', 'actor_id': 'u1', 'actor_roles': ['intern'], 'channel': 'cli', 'text': 'Book gym and what time are services?'
    }).json()
    assert r['lane'] == 'HYBRID'
    assert r['plan'] is not None
    assert r.get('answer')