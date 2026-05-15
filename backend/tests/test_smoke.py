"""Phase-2a smoke tests: app boots, DB seeds, zones + vehicles + missions exist."""
from __future__ import annotations

from app.models import Mission, Vehicle, ZoneCount
from app.zones import ZONES


def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_init_db_seeds_20_zones(session):
    rows = session.query(ZoneCount).all()
    assert len(rows) == 20
    zone_ids = {r.zone_id for r in rows}
    assert zone_ids == set(ZONES)
    for r in rows:
        assert r.entry_count == 0


def test_init_db_seeds_50_vehicles_with_missions(session):
    vehicles = session.query(Vehicle).all()
    assert len(vehicles) == 50
    for v in vehicles:
        assert v.status == "idle"

    expected_ids = {f"v-{i:02d}" for i in range(50)}
    assert {v.vehicle_id for v in vehicles} == expected_ids

    active_missions = (
        session.query(Mission).filter(Mission.status == "active").all()
    )
    assert len(active_missions) == 50
    assert {m.vehicle_id for m in active_missions} == expected_ids
