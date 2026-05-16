"""Phase 2b ingestion endpoint tests."""
from __future__ import annotations

import concurrent.futures

from app.models import Anomaly, TelemetryEvent, Vehicle, ZoneCount


def _event(**overrides):
    base = {
        "vehicle_id": "v-01",
        "timestamp": "2026-05-15T12:00:00+00:00",
        "lat": 37.41,
        "lon": -122.08,
        "battery_pct": 80.0,
        "speed_mps": 1.0,
        "status": "moving",
        "error_codes": [],
        "zone_entered": None,
    }
    base.update(overrides)
    return base


def test_post_single_event_201_returns_accepted_1(client, session):
    r = client.post("/telemetry", json=_event(battery_pct=77.5))
    assert r.status_code == 202
    assert r.json() == {"accepted": 1}

    assert session.query(TelemetryEvent).count() == 1
    v = session.query(Vehicle).filter_by(vehicle_id="v-01").one()
    assert v.battery_pct == 77.5
    assert session.query(Anomaly).count() == 0


def test_post_batch_of_5_events(client, session):
    batch = [
        _event(vehicle_id=f"v-0{i}", timestamp=f"2026-05-15T12:00:0{i}+00:00")
        for i in range(5)
    ]
    r = client.post("/telemetry", json=batch)
    assert r.status_code == 202
    assert r.json() == {"accepted": 5}
    assert session.query(TelemetryEvent).count() == 5


def test_zone_entered_increments_count(client, session):
    r = client.post("/telemetry", json=_event(zone_entered="aisle_a"))
    assert r.status_code == 202
    row = session.query(ZoneCount).filter_by(zone_id="aisle_a").one()
    assert row.entry_count == 1


def test_empty_vehicle_id_rejected_with_422(client):
    """F-015: vehicle_id must match `^v-\\d{2,4}$`."""
    bad = _event(vehicle_id="")
    r = client.post("/telemetry", json=bad)
    assert r.status_code == 422


def test_arbitrary_vehicle_id_rejected_with_422(client):
    bad = _event(vehicle_id="not-a-vehicle")
    r = client.post("/telemetry", json=bad)
    assert r.status_code == 422


def test_unknown_zone_logged_but_not_error(client, session):
    r = client.post("/telemetry", json=_event(zone_entered="nonexistent_zone"))
    assert r.status_code == 202
    # All known zones still 0.
    for z in session.query(ZoneCount).all():
        assert z.entry_count == 0


def test_overspeed_creates_anomaly(client, session):
    r = client.post("/telemetry", json=_event(speed_mps=7.5))
    assert r.status_code == 202
    rows = session.query(Anomaly).filter_by(code="overspeed").all()
    assert len(rows) == 1
    assert rows[0].vehicle_id == "v-01"


def test_status_fault_creates_anomaly(client, session):
    r = client.post("/telemetry", json=_event(status="fault"))
    assert r.status_code == 202
    rows = session.query(Anomaly).filter_by(code="status_fault").all()
    assert len(rows) == 1


def test_error_codes_present_creates_anomaly(client, session):
    r = client.post("/telemetry", json=_event(error_codes=["E_BATTERY_HOT"]))
    assert r.status_code == 202
    rows = session.query(Anomaly).filter_by(code="error_codes_present").all()
    assert len(rows) == 1
    assert rows[0].detail == "E_BATTERY_HOT"


def test_battery_drop_creates_anomaly_only_on_second_event(client, session):
    r1 = client.post(
        "/telemetry",
        json=_event(battery_pct=90.0, timestamp="2026-05-15T12:00:00+00:00"),
    )
    assert r1.status_code == 202
    assert session.query(Anomaly).filter_by(code="battery_drop").count() == 0

    r2 = client.post(
        "/telemetry",
        json=_event(battery_pct=60.0, timestamp="2026-05-15T12:00:01+00:00"),
    )
    assert r2.status_code == 202
    rows = session.query(Anomaly).filter_by(code="battery_drop").all()
    assert len(rows) == 1
    assert "drop=30.0pp" in rows[0].detail


def test_200_concurrent_zone_entered_all_counted(client, session):
    """The critical concurrency test. 200 POSTs against the same zone with
    32 worker threads. Final entry_count must be exactly 200 — proves the
    SQL-side arithmetic is not lossy under SQLite's writer serialization.
    """

    def fire(i: int):
        vid = f"v-{i % 50:02d}"
        body = _event(
            vehicle_id=vid,
            timestamp=f"2026-05-15T12:{(i // 60) % 60:02d}:{i % 60:02d}+00:00",
            zone_entered="charging_bay_1",
        )
        return client.post("/telemetry", json=body)

    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as ex:
        futures = [ex.submit(fire, i) for i in range(200)]
        responses = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(r.status_code == 202 for r in responses)

    session.expire_all()
    row = session.query(ZoneCount).filter_by(zone_id="charging_bay_1").one()
    assert row.entry_count == 200, f"expected 200, got {row.entry_count}"
