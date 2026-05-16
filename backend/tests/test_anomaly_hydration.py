"""F-003 regression: the `battery_drop` cache must be hydrated from the
`vehicles` table on first sight, so the first telemetry event after a
process restart still produces a `battery_drop` row when the drop is large
enough.

We simulate a restart by clearing the in-process cache between two POSTs.
The second POST hits a fresh-cache path; without `anomaly.hydrate(...)` it
would silently skip `battery_drop`.
"""
from __future__ import annotations

from app import anomaly
from app.models import Anomaly


def _event(**overrides):
    base = {
        "vehicle_id": "v-00",
        "timestamp": "2026-05-15T12:00:00+00:00",
        "lat": 37.41,
        "lon": -122.08,
        "battery_pct": 90.0,
        "speed_mps": 1.0,
        "status": "moving",
        "error_codes": [],
        "zone_entered": None,
    }
    base.update(overrides)
    return base


def test_battery_drop_fires_on_first_event_after_simulated_restart(client, session):
    # 1. Seed: v-00 at 90 % battery.
    r1 = client.post(
        "/telemetry",
        json=_event(timestamp="2026-05-15T12:00:00+00:00", battery_pct=90.0),
    )
    assert r1.status_code == 202

    # 2. Simulate a process restart — wipe the in-memory anomaly cache.
    #    The `vehicles` row still records battery_pct=90, last_timestamp=...
    anomaly._reset_cache_for_tests()
    assert "v-00" not in anomaly._last_event

    # 3. Second event 30 pp lower. Without hydration, this would produce
    #    zero anomalies (the cache is empty so prior_snapshot is None).
    r2 = client.post(
        "/telemetry",
        json=_event(timestamp="2026-05-15T12:00:01+00:00", battery_pct=60.0),
    )
    assert r2.status_code == 202

    drops = session.query(Anomaly).filter_by(code="battery_drop").all()
    assert len(drops) == 1, f"expected 1 battery_drop, got {len(drops)}: {[d.detail for d in drops]}"
    assert "prev=90" in drops[0].detail
    assert "curr=60" in drops[0].detail


def test_hydrate_is_a_noop_when_cache_already_warm(client, session):
    # Warm the cache via a normal event.
    client.post("/telemetry", json=_event(battery_pct=80.0))
    before = dict(anomaly._last_event["v-00"])

    # Calling hydrate again must not overwrite a real cached value.
    from app import db as db_module

    s = db_module.SessionLocal()
    try:
        anomaly.hydrate("v-00", s)
    finally:
        s.close()

    assert anomaly._last_event["v-00"] == before


def test_hydrate_skips_unknown_vehicle(client, session):
    from app import db as db_module

    s = db_module.SessionLocal()
    try:
        anomaly.hydrate("v-99-not-seeded", s)
    finally:
        s.close()

    assert "v-99-not-seeded" not in anomaly._last_event
