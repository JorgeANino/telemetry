"""Phase 2d — read endpoints tests.

State is built via the actual POST /telemetry and POST /vehicles/{id}/status
endpoints so these tests double as smoke tests of the write side.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.zones import ZONES


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(**overrides):
    base = {
        "vehicle_id": "v-00",
        "timestamp": _now_iso(),
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


# --------------------------------------------------------------------------- #
# /zones/counts                                                               #
# --------------------------------------------------------------------------- #


def test_zones_counts_returns_all_20_zones_zeroed_initially(client):
    r = client.get("/zones/counts")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["counts"].keys()) == set(ZONES)
    assert all(v == 0 for v in body["counts"].values())


def test_zones_counts_reflects_increments(client):
    # 3 events with zone_entered="aisle_a"
    for i in range(3):
        r = client.post(
            "/telemetry",
            json=_event(
                vehicle_id=f"v-0{i}",
                timestamp=f"2026-05-15T12:00:0{i}+00:00",
                zone_entered="aisle_a",
            ),
        )
        assert r.status_code == 202

    # 1 event with zone_entered="pack_station"
    r = client.post(
        "/telemetry",
        json=_event(
            vehicle_id="v-10",
            timestamp="2026-05-15T12:00:10+00:00",
            zone_entered="pack_station",
        ),
    )
    assert r.status_code == 202

    body = client.get("/zones/counts").json()
    assert body["counts"]["aisle_a"] == 3
    assert body["counts"]["pack_station"] == 1
    for z in ZONES:
        if z not in ("aisle_a", "pack_station"):
            assert body["counts"][z] == 0, f"expected {z}=0, got {body['counts'][z]}"


# --------------------------------------------------------------------------- #
# /vehicles                                                                   #
# --------------------------------------------------------------------------- #


def test_list_vehicles_returns_50_sorted(client):
    r = client.get("/vehicles")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 50
    ids = [row["vehicle_id"] for row in body]
    assert ids == sorted(ids)
    # Each row should have the documented shape.
    for row in body:
        assert set(row.keys()) == {
            "vehicle_id",
            "status",
            "battery_pct",
            "last_timestamp",
        }
        assert row["status"] in ("idle", "moving", "charging", "fault")


# --------------------------------------------------------------------------- #
# /fleet/state                                                                #
# --------------------------------------------------------------------------- #


def test_fleet_state_initial_all_idle(client):
    r = client.get("/fleet/state")
    assert r.status_code == 200, r.text
    assert r.json() == {"idle": 50, "moving": 0, "charging": 0, "fault": 0}


def test_fleet_state_after_transitions(client):
    # Transition v-00 -> moving, v-01 -> charging, v-02 -> fault via status endpoint
    assert (
        client.post("/vehicles/v-00/status", json={"new_status": "moving"}).status_code
        == 200
    )
    assert (
        client.post(
            "/vehicles/v-01/status", json={"new_status": "charging"}
        ).status_code
        == 200
    )
    assert (
        client.post("/vehicles/v-02/status", json={"new_status": "fault"}).status_code
        == 200
    )

    # And drive v-03 -> moving via telemetry (the ingest upserts status).
    r = client.post(
        "/telemetry",
        json=_event(
            vehicle_id="v-03",
            timestamp="2026-05-15T12:00:00+00:00",
            status="moving",
        ),
    )
    assert r.status_code == 202

    body = client.get("/fleet/state").json()
    assert body == {"idle": 46, "moving": 2, "charging": 1, "fault": 1}


# --------------------------------------------------------------------------- #
# /anomalies                                                                  #
# --------------------------------------------------------------------------- #


def test_anomalies_empty_initially(client):
    r = client.get("/anomalies")
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_anomalies_default_1h_window_includes_recent(client):
    # Use a "now" timestamp so the default 1h window catches it.
    ts = _now_iso()
    r = client.post(
        "/telemetry",
        json=_event(vehicle_id="v-00", timestamp=ts, speed_mps=7.5),
    )
    assert r.status_code == 202

    rows = client.get("/anomalies").json()
    assert len(rows) >= 1
    overspeeds = [r for r in rows if r["code"] == "overspeed"]
    assert len(overspeeds) >= 1
    assert overspeeds[0]["vehicle_id"] == "v-00"


def test_anomalies_filter_by_vehicle(client):
    ts_base = datetime.now(timezone.utc)
    # Overspeed for v-00
    assert (
        client.post(
            "/telemetry",
            json=_event(
                vehicle_id="v-00",
                timestamp=ts_base.isoformat(),
                speed_mps=7.5,
            ),
        ).status_code
        == 202
    )
    # Overspeed for v-01
    assert (
        client.post(
            "/telemetry",
            json=_event(
                vehicle_id="v-01",
                timestamp=(ts_base + timedelta(seconds=1)).isoformat(),
                speed_mps=8.0,
            ),
        ).status_code
        == 202
    )

    rows = client.get("/anomalies?vehicle_id=v-00").json()
    assert len(rows) == 1
    assert rows[0]["vehicle_id"] == "v-00"
    assert rows[0]["code"] == "overspeed"


def test_anomalies_filter_by_time_range(client):
    # Very old overspeed event — outside the default 1h window.
    r = client.post(
        "/telemetry",
        json=_event(
            vehicle_id="v-00",
            timestamp="2020-01-01T00:00:00+00:00",
            speed_mps=7.5,
        ),
    )
    assert r.status_code == 202

    # Default window (last 1h) should not see it.
    assert client.get("/anomalies").json() == []

    # Explicit wide window should.
    rows = client.get(
        "/anomalies?from=2019-01-01T00:00:00+00:00&to=2021-01-01T00:00:00+00:00"
    ).json()
    assert len(rows) == 1
    assert rows[0]["vehicle_id"] == "v-00"
    assert rows[0]["code"] == "overspeed"


def test_anomalies_limit_clamp(client):
    ts_base = datetime.now(timezone.utc)
    for i in range(5):
        r = client.post(
            "/telemetry",
            json=_event(
                vehicle_id=f"v-0{i}",
                timestamp=(ts_base + timedelta(seconds=i)).isoformat(),
                speed_mps=7.5,
            ),
        )
        assert r.status_code == 202

    rows = client.get("/anomalies?limit=2").json()
    assert len(rows) == 2


def test_anomalies_limit_rejects_invalid(client):
    assert client.get("/anomalies?limit=0").status_code == 422
    assert client.get("/anomalies?limit=10000").status_code == 422
