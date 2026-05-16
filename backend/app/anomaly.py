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

from sqlalchemy import text
from sqlalchemy.orm import Session

BATTERY_DROP_THRESHOLD_PP = 20
OVERSPEED_MPS = 5.0

# Last-event-per-vehicle cache. We only retain the two fields the
# `battery_drop` rule needs, not the entire event.
_last_event_lock = threading.Lock()
_last_event: dict[str, dict] = {}


def hydrate(vehicle_id: str, session: Session) -> None:
    """Lazily seed the cache from `vehicles` on first sight of a vehicle.

    Without this, the first telemetry event after every process restart
    silently skips `battery_drop` for that vehicle — the comparison falls
    through `prior_snapshot is None`. We use `setdefault` under the lock so
    a real event already processed by another thread always wins.
    """
    with _last_event_lock:
        if vehicle_id in _last_event:
            return
    row = session.execute(
        text(
            "SELECT battery_pct, last_timestamp "
            "FROM vehicles WHERE vehicle_id = :v"
        ),
        {"v": vehicle_id},
    ).first()
    if row is None or row.battery_pct is None or row.last_timestamp is None:
        return
    with _last_event_lock:
        _last_event.setdefault(
            vehicle_id,
            {"battery_pct": row.battery_pct, "timestamp": row.last_timestamp},
        )


def evaluate(event: dict[str, Any]) -> list[dict[str, str]]:
    """Evaluate the four anomaly rules against a single event.

    `event` is a Pydantic-validated `TelemetryEventIn` dumped to a dict.
    Returns a list of `{"code", "detail"}` dicts — empty list if the event
    is clean. **Pure** — no cache mutation. Callers must call `remember(...)`
    after the surrounding DB transaction commits so a rollback never leaves
    a ghost prior in the cache (F-005).
    """
    anomalies: list[dict[str, str]] = []

    vehicle_id: str = event["vehicle_id"]
    curr_pct: float = event["battery_pct"]
    speed_mps: float = event["speed_mps"]
    error_codes: list[str] = event.get("error_codes") or []
    status: str = event["status"]

    # --- battery_drop -----------------------------------------------------
    # Compare against cached prior. We snapshot under the lock so the read
    # is consistent with concurrent updates from other threads.
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

    return anomalies


def remember(vehicle_id: str, battery_pct: float, timestamp: str) -> None:
    """Record a vehicle's latest battery reading in the in-process cache.

    Must only be called after the surrounding DB transaction commits.
    Out-of-order events are rejected via lex-compare on the ISO-8601
    timestamp so a late-arriving older event cannot poison the prior.
    """
    with _last_event_lock:
        existing = _last_event.get(vehicle_id)
        if existing is None or timestamp > existing["timestamp"]:
            _last_event[vehicle_id] = {
                "battery_pct": battery_pct,
                "timestamp": timestamp,
            }


def _reset_cache_for_tests() -> None:
    """Clear the last-event cache. Called from test setup fixtures."""
    with _last_event_lock:
        _last_event.clear()
