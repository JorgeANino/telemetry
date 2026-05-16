"""Telemetry ingest router. POST /telemetry.

Accepts either a single TelemetryEventIn or a JSON array of them. For each
event we:

  1. Insert a TelemetryEvent row.
  2. Upsert the Vehicle row's last-state fields (NOT status_version — that
     belongs to the explicit status-update endpoint).
  3. If `zone_entered` is non-null, increment the zone counter via
     `UPDATE ... SET entry_count = entry_count + 1 WHERE zone_id = ?`. The
     arithmetic happens in SQL — never as a Python read-modify-write — so
     concurrent requests cannot lose a count. Unknown zone_ids are logged
     and skipped.
  4. Run anomaly.evaluate() and insert any rows it returns.

Concurrency: each request gets its own session via Depends(get_session).
We deliberately do NOT introduce a threading.Lock here — SQLite's writer
serialization plus the SQL-side arithmetic is the whole correctness story.
Only anomaly.py uses a lock, and only to protect its in-process dict.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .. import anomaly
from ..db import get_session
from ..models import Anomaly, TelemetryEvent, Vehicle
from ..schemas import TelemetryEventIn

router = APIRouter(tags=["telemetry"])

logger = logging.getLogger(__name__)


@router.post("/telemetry")
def post_telemetry(
    payload: TelemetryEventIn | list[TelemetryEventIn],
    session: Session = Depends(get_session),
):
    events: list[TelemetryEventIn] = (
        payload if isinstance(payload, list) else [payload]
    )

    # Stage cache updates until the transaction commits — a rollback must
    # not leave a ghost prior in the in-memory cache (F-005).
    cache_updates: list[tuple[str, float, str]] = []

    try:
        for event in events:
            # 0. Hydrate the per-vehicle anomaly cache from the DB on first
            #    sight (ADR §2). MUST run before the upsert below — otherwise
            #    the SELECT sees the row we're about to write and seeds the
            #    cache with the current event's battery, defeating
            #    `battery_drop` for the post-restart event.
            anomaly.hydrate(event.vehicle_id, session)

            # 1. Raw telemetry row.
            session.add(
                TelemetryEvent(
                    vehicle_id=event.vehicle_id,
                    timestamp=event.timestamp,
                    lat=event.lat,
                    lon=event.lon,
                    battery_pct=event.battery_pct,
                    speed_mps=event.speed_mps,
                    status=event.status,
                    error_codes_json=json.dumps(event.error_codes),
                    zone_entered=event.zone_entered,
                )
            )

            # 2. Vehicle upsert — refresh latest-state columns. We intentionally
            #    do NOT touch status_version; that's owned by the status-update
            #    endpoint.
            stmt = sqlite_insert(Vehicle).values(
                vehicle_id=event.vehicle_id,
                status=event.status,
                battery_pct=event.battery_pct,
                last_lat=event.lat,
                last_lon=event.lon,
                last_timestamp=event.timestamp,
                status_version=0,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[Vehicle.vehicle_id],
                set_={
                    "status": stmt.excluded.status,
                    "battery_pct": stmt.excluded.battery_pct,
                    "last_lat": stmt.excluded.last_lat,
                    "last_lon": stmt.excluded.last_lon,
                    "last_timestamp": stmt.excluded.last_timestamp,
                },
            )
            session.execute(stmt)

            # 3. Zone counter — arithmetic in SQL.
            if event.zone_entered is not None:
                result = session.execute(
                    text(
                        "UPDATE zone_counts "
                        "SET entry_count = entry_count + 1 "
                        "WHERE zone_id = :z"
                    ),
                    {"z": event.zone_entered},
                )
                if result.rowcount == 0:
                    logger.warning(
                        "telemetry: unknown zone_entered=%r for vehicle=%r — skipping",
                        event.zone_entered,
                        event.vehicle_id,
                    )

            # 4. Anomaly evaluation. Pure function — cache write is deferred
            #    until after commit (see step 5).
            for a in anomaly.evaluate(event.model_dump()):
                session.add(
                    Anomaly(
                        vehicle_id=event.vehicle_id,
                        timestamp=event.timestamp,
                        code=a["code"],
                        detail=a["detail"],
                    )
                )
            cache_updates.append(
                (event.vehicle_id, event.battery_pct, event.timestamp)
            )

        session.commit()
    except Exception:
        session.rollback()
        raise

    # 5. Now that the transaction is durable, update the anomaly cache.
    for vid, pct, ts in cache_updates:
        anomaly.remember(vid, pct, ts)

    return JSONResponse({"accepted": len(events)}, status_code=202)
