"""F-005 regression: a failed commit on the telemetry write path must NOT
leave a stale entry in the in-process anomaly cache. Previously `evaluate()`
mutated `_last_event` mid-transaction; the cache update has been moved
behind `session.commit()` and is gated on the success of the transaction.
"""
from __future__ import annotations

import pytest

from app import anomaly
from app import db as db_module


def _event(**overrides):
    base = {
        "vehicle_id": "v-00",
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


def test_failed_commit_does_not_poison_anomaly_cache(client, monkeypatch):
    """Force the request-scoped session's commit to raise. The HTTP request
    should bubble a 500, and the anomaly cache must be unchanged afterwards.
    """
    assert "v-00" not in anomaly._last_event, "precondition: cache empty"

    # Monkeypatch SessionLocal so every new session has commit() that raises.
    original = db_module.SessionLocal

    def _broken_session_factory(*args, **kwargs):
        s = original(*args, **kwargs)
        s.commit = lambda: (_ for _ in ()).throw(RuntimeError("simulated"))
        return s

    monkeypatch.setattr(db_module, "SessionLocal", _broken_session_factory)

    # TestClient re-raises server exceptions by default, which is the
    # behaviour we want here — we're not asserting on the HTTP response,
    # we're asserting the cache stayed clean after the rollback path.
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            client.post(
                "/telemetry",
                json=_event(
                    battery_pct=75.0, timestamp="2026-05-15T12:00:05+00:00"
                ),
            )
    finally:
        monkeypatch.setattr(db_module, "SessionLocal", original)

    # The whole point of the fix: cache must still be empty.
    assert "v-00" not in anomaly._last_event, (
        f"cache leaked across failed commit: {anomaly._last_event!r}"
    )


def test_successful_commit_updates_cache(client):
    """The happy-path counterpart — confirms that the post-commit `remember`
    call still actually populates the cache.
    """
    assert "v-00" not in anomaly._last_event
    r = client.post(
        "/telemetry",
        json=_event(battery_pct=72.5, timestamp="2026-05-15T12:00:00+00:00"),
    )
    assert r.status_code == 202
    assert anomaly._last_event["v-00"] == {
        "battery_pct": 72.5,
        "timestamp": "2026-05-15T12:00:00+00:00",
    }
