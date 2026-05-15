"""Pure unit tests for the anomaly evaluator. No HTTP, no DB."""
from __future__ import annotations

import pytest

from app import anomaly


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


@pytest.fixture(autouse=True)
def _clean_cache():
    anomaly._reset_cache_for_tests()
    yield
    anomaly._reset_cache_for_tests()


def test_battery_drop_fires_on_second_event():
    # First event seeds the cache; should produce no anomaly on its own.
    assert anomaly.evaluate(_event(battery_pct=90.0, timestamp="2026-05-15T12:00:00+00:00")) == []
    # Second event 30 pp lower -> battery_drop.
    out = anomaly.evaluate(_event(battery_pct=60.0, timestamp="2026-05-15T12:00:01+00:00"))
    codes = [a["code"] for a in out]
    assert "battery_drop" in codes
    drop = next(a for a in out if a["code"] == "battery_drop")
    assert "prev=90.0" in drop["detail"]
    assert "curr=60.0" in drop["detail"]
    assert "30.0pp" in drop["detail"]


def test_overspeed_fires_above_threshold():
    out = anomaly.evaluate(_event(speed_mps=7.5))
    codes = [a["code"] for a in out]
    assert "overspeed" in codes
    detail = next(a["detail"] for a in out if a["code"] == "overspeed")
    assert "7.5" in detail


def test_overspeed_not_fired_at_threshold():
    # Strictly greater than 5.0
    out = anomaly.evaluate(_event(speed_mps=5.0))
    assert [a["code"] for a in out] == []


def test_error_codes_present_fires_on_nonempty():
    out = anomaly.evaluate(_event(error_codes=["E_BATTERY_HOT", "E_MOTOR"]))
    codes = [a["code"] for a in out]
    assert "error_codes_present" in codes
    detail = next(a["detail"] for a in out if a["code"] == "error_codes_present")
    assert detail == "E_BATTERY_HOT,E_MOTOR"


def test_status_fault_fires_when_status_is_fault():
    out = anomaly.evaluate(_event(status="fault"))
    codes = [a["code"] for a in out]
    assert "status_fault" in codes


def test_multiple_rules_emit_multiple_rows():
    # Seed prior battery to trigger battery_drop on the next event.
    anomaly.evaluate(_event(battery_pct=95.0, timestamp="2026-05-15T12:00:00+00:00"))
    out = anomaly.evaluate(
        _event(
            battery_pct=50.0,
            timestamp="2026-05-15T12:00:01+00:00",
            speed_mps=9.0,
            status="fault",
            error_codes=["E_MOTOR"],
        )
    )
    codes = {a["code"] for a in out}
    assert codes == {
        "battery_drop",
        "overspeed",
        "error_codes_present",
        "status_fault",
    }
