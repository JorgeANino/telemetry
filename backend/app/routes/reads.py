"""Read-side endpoints: anomalies, fleet state, zone counts (Phase 2d).

All three handlers are deliberately single-statement reads against the
SQLite WAL snapshot. Under WAL, a SELECT sees a single point-in-time view of
the database; concurrent writers cannot interleave partial state into the
result. That gives us the "safe under concurrent updates" guarantee the spec
asks for on the aggregate fleet endpoint, without any explicit locking.

We use raw `text()` queries rather than the ORM here — these are read-only
projections of fixed shape, and the SQL is easier to read than the
equivalent ORM construction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_session
from ..zones import ZONES

router = APIRouter(tags=["reads"])

# Statuses the fleet-state endpoint must always return as keys, even when the
# GROUP BY did not produce a row for that status.
_FLEET_STATUSES = ("idle", "moving", "charging", "fault")

# ADR §2: default anomaly window when neither from_ nor to is supplied.
_DEFAULT_ANOMALY_WINDOW = timedelta(hours=1)


@router.get("/anomalies")
def get_anomalies(
    vehicle_id: Optional[str] = None,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    """Return recent anomalies, optionally filtered by vehicle and time range.

    Defaults to the last 1 hour when neither `from` nor `to` is supplied
    (ADR §2). Ordering is `(timestamp DESC, id DESC)` so the newest event
    wins ties and pagination behaviour is deterministic.
    """
    clauses: list[str] = []
    params: dict[str, object] = {"limit": limit}

    # Apply the 1-hour default ONLY when neither bound is supplied. If the
    # caller passed one bound, we trust them and do not synthesize the other.
    if from_ is None and to is None:
        default_from = (
            datetime.now(timezone.utc) - _DEFAULT_ANOMALY_WINDOW
        ).isoformat()
        clauses.append("timestamp >= :from_")
        params["from_"] = default_from
    else:
        if from_ is not None:
            clauses.append("timestamp >= :from_")
            params["from_"] = from_
        if to is not None:
            clauses.append("timestamp <= :to")
            params["to"] = to

    if vehicle_id is not None:
        clauses.append("vehicle_id = :vehicle_id")
        params["vehicle_id"] = vehicle_id

    where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = (
        "SELECT id, vehicle_id, timestamp, code, detail "
        "FROM anomalies"
        f"{where_sql} "
        "ORDER BY timestamp DESC, id DESC "
        "LIMIT :limit"
    )

    rows = session.execute(text(sql), params).all()
    return [
        {
            "id": r.id,
            "vehicle_id": r.vehicle_id,
            "timestamp": r.timestamp,
            "code": r.code,
            "detail": r.detail,
        }
        for r in rows
    ]


@router.get("/vehicles")
def list_vehicles(session: Session = Depends(get_session)):
    """All vehicles with their latest snapshot state.

    Single SELECT — naturally consistent under WAL like /fleet/state.
    """
    rows = session.execute(
        text(
            "SELECT vehicle_id, status, battery_pct, last_timestamp "
            "FROM vehicles ORDER BY vehicle_id"
        )
    ).all()
    return [
        {
            "vehicle_id": r.vehicle_id,
            "status": r.status,
            "battery_pct": r.battery_pct,
            "last_timestamp": r.last_timestamp,
        }
        for r in rows
    ]


@router.get("/fleet/state")
def get_fleet_state(session: Session = Depends(get_session)):
    """Per-status vehicle counts. Always returns all four statuses as keys."""
    # Snapshot consistent under WAL: a single SELECT sees a single point-in-time view; concurrent writers do not interleave into the result.
    rows = session.execute(
        text("SELECT status, COUNT(*) AS cnt FROM vehicles GROUP BY status")
    ).all()
    counts = {s: 0 for s in _FLEET_STATUSES}
    for r in rows:
        # Defensive: ignore any unknown status that might somehow slip in.
        if r.status in counts:
            counts[r.status] = r.cnt
    return counts


@router.get("/zones/counts")
def get_zone_counts(session: Session = Depends(get_session)):
    """Per-zone entry counts. All 20 seeded zones are guaranteed present."""
    rows = session.execute(
        text("SELECT zone_id, entry_count FROM zone_counts ORDER BY zone_id")
    ).all()
    counts = {r.zone_id: r.entry_count for r in rows}
    # Defensive: seed guarantees this, but if a zone row were ever missing
    # we still return it as 0 rather than dropping the key.
    for z in ZONES:
        counts.setdefault(z, 0)
    return {"counts": counts}
