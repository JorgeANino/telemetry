"""Phase 2c — status update + fault transition tests.

The critical test is `test_10_concurrent_fault_transitions_idempotent`, which
exercises the BEGIN IMMEDIATE + status re-read guard in the fault branch:
ten concurrent fault POSTs against the same vehicle must produce exactly one
status flip, one maintenance record, and one cancelled mission.
"""
from __future__ import annotations

import concurrent.futures

from app.models import MaintenanceRecord, Mission, Vehicle


def test_status_update_to_moving_bumps_version(client, session):
    r = client.post("/vehicles/v-00/status", json={"new_status": "moving"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["vehicle_id"] == "v-00"
    assert body["status"] == "moving"
    assert body["status_version"] == 1

    session.expire_all()
    v = session.query(Vehicle).filter_by(vehicle_id="v-00").one()
    assert v.status == "moving"
    assert v.status_version == 1

    missions = session.query(Mission).filter_by(vehicle_id="v-00").all()
    assert len(missions) == 1
    assert missions[0].status == "active"

    assert session.query(MaintenanceRecord).filter_by(vehicle_id="v-00").count() == 0


def test_status_update_unknown_vehicle_returns_404(client, session):
    r = client.post("/vehicles/nope/status", json={"new_status": "moving"})
    assert r.status_code == 404
    assert r.json() == {"detail": "vehicle not found"}


def test_status_update_to_fault_cancels_mission_and_creates_maintenance(client, session):
    r = client.post("/vehicles/v-01/status", json={"new_status": "fault"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "fault"
    assert body["status_version"] == 1

    session.expire_all()
    v = session.query(Vehicle).filter_by(vehicle_id="v-01").one()
    assert v.status == "fault"
    assert v.status_version == 1

    missions = session.query(Mission).filter_by(vehicle_id="v-01").all()
    assert len(missions) == 1
    assert missions[0].status == "cancelled"
    assert missions[0].cancelled_at is not None

    records = session.query(MaintenanceRecord).filter_by(vehicle_id="v-01").all()
    assert len(records) == 1
    assert records[0].reason == "fault_transition"


def test_10_concurrent_fault_transitions_idempotent(client, session):
    """Ten concurrent fault POSTs must produce exactly one status flip, one
    maintenance record, one cancelled mission. The BEGIN IMMEDIATE writer
    lock serializes the writers; the status re-read inside the lock is what
    makes writer #N+1 a no-op.
    """

    def fire(_i: int):
        return client.post("/vehicles/v-02/status", json={"new_status": "fault"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(fire, i) for i in range(10)]
        responses = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(r.status_code == 200 for r in responses), [
        (r.status_code, r.text) for r in responses
    ]

    session.expire_all()
    v = session.query(Vehicle).filter_by(vehicle_id="v-02").one()
    assert v.status == "fault"
    assert v.status_version == 1, f"expected status_version=1, got {v.status_version}"

    missions = session.query(Mission).filter_by(vehicle_id="v-02").all()
    assert len(missions) == 1, f"expected 1 mission row, got {len(missions)}"
    assert missions[0].status == "cancelled"

    records = session.query(MaintenanceRecord).filter_by(vehicle_id="v-02").all()
    assert len(records) == 1, f"expected 1 maintenance record, got {len(records)}"


def test_fault_after_fault_is_noop(client, session):
    r1 = client.post("/vehicles/v-03/status", json={"new_status": "fault"})
    assert r1.status_code == 200
    r2 = client.post("/vehicles/v-03/status", json={"new_status": "fault"})
    assert r2.status_code == 200

    session.expire_all()
    v = session.query(Vehicle).filter_by(vehicle_id="v-03").one()
    assert v.status == "fault"
    assert v.status_version == 1

    records = session.query(MaintenanceRecord).filter_by(vehicle_id="v-03").all()
    assert len(records) == 1
