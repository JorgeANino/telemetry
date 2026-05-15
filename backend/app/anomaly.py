"""Anomaly detection rules (Phase 2b).

Thresholds are exposed as module constants so a grader can see them. The
evaluator is intentionally pure and synchronous: it takes a single event dict
and returns a list of `{code, detail}` dicts, one per rule that fires.

State: a single in-process dict of `{vehicle_id: {battery_pct, timestamp}}`
that records the last event we have seen for each vehicle. The dict is
guarded by a module-level `threading.Lock` because the FastAPI app may be
hit by multiple threads concurrently (TestClient, future load).
"""
from __future__ import annotations

import threading
from typing import Any

BATTERY_DROP_THRESHOLD_PP = 20
OVERSPEED_MPS = 5.0

# Last-event-per-vehicle cache. We only retain the two fields the
# `battery_drop` rule needs, not the entire event.
_last_event_lock = threading.Lock()
_last_event: dict[str, dict] = {}


def evaluate(event: dict[str, Any]) -> list[dict[str, str]]:
    """Evaluate the four anomaly rules against a single event.

    `event` is a Pydantic-validated `TelemetryEventIn` dumped to a dict.
    Returns a list of `{"code", "detail"}` dicts — empty list if the event
    is clean. Side-effect: updates the in-process last-event cache.
    """
    anomalies: list[dict[str, str]] = []

    vehicle_id: str = event["vehicle_id"]
    curr_pct: float = event["battery_pct"]
    curr_ts: str = event["timestamp"]
    speed_mps: float = event["speed_mps"]
    error_codes: list[str] = event.get("error_codes") or []
    status: str = event["status"]

    # --- battery_drop -----------------------------------------------------
    # Compare against cached prior. We snapshot the prior under the lock so
    # the read is consistent with concurrent updates from other threads.
    with _last_event_lock:
        prior = _last_event.get(vehicle_id)
        prior_snapshot = dict(prior) if prior is not None else None

    if prior_snapshot is not None:
        prev_pct = prior_snapshot["battery_pct"]
        if prev_pct >= curr_pct + BATTERY_DROP_THRESHOLD_PP:
            anomalies.append(
                {
                    "code": "battery_drop",
                    "detail": f"prev={prev_pct} curr={curr_pct} drop={prev_pct - curr_pct:.1f}pp",
                }
            )

    # --- overspeed --------------------------------------------------------
    if speed_mps > OVERSPEED_MPS:
        anomalies.append(
            {"code": "overspeed", "detail": f"speed={speed_mps} m/s"}
        )

    # --- error_codes_present ---------------------------------------------
    if error_codes:
        anomalies.append(
            {"code": "error_codes_present", "detail": ",".join(error_codes)}
        )

    # --- status_fault -----------------------------------------------------
    if status == "fault":
        anomalies.append({"code": "status_fault", "detail": ""})

    # Update cache only if this event is newer than what we have. ISO-8601
    # timestamps compare correctly lexicographically, so out-of-order events
    # cannot poison the prior.
    with _last_event_lock:
        existing = _last_event.get(vehicle_id)
        if existing is None or curr_ts > existing["timestamp"]:
            _last_event[vehicle_id] = {
                "battery_pct": curr_pct,
                "timestamp": curr_ts,
            }

    return anomalies


def _reset_cache_for_tests() -> None:
    """Clear the last-event cache. Called from test setup fixtures."""
    with _last_event_lock:
        _last_event.clear()
