"""Vehicle status update router. POST /vehicles/{vehicle_id}/status.

Two paths:

- Non-fault transitions (idle/moving/charging) are a single UPDATE statement
  that also bumps `status_version` arithmetically in SQL. No multi-statement
  atomicity concerns; the request handler commits and returns.

- The fault transition is the multi-statement atomic operation called out in
  the spec. We open a dedicated session, issue `BEGIN IMMEDIATE` to grab
  SQLite's writer/reserved lock up front, re-read the vehicle status inside
  the lock, and either:
    * short-circuit (idempotent no-op) if the vehicle is already 'fault', or
    * flip status + bump version, cancel the active mission, and insert a
      maintenance record, then commit.

  This is intentionally not using `Depends(get_session)` for the fault branch
  so we control the transaction boundary explicitly and don't fight FastAPI's
  dependency lifecycle around explicit BEGIN/COMMIT.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import db
from ..db import get_session
from ..schemas import StatusUpdateIn

router = APIRouter(tags=["status"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/vehicles/{vehicle_id}/status")
def update_status(
    vehicle_id: str,
    payload: StatusUpdateIn,
    session: Session = Depends(get_session),
):
    new_status = payload.new_status

    # 1. Confirm the vehicle exists. Doing this with a SELECT before any write
    #    keeps the 404 path cheap and free of side effects.
    row = session.execute(
        text(
            "SELECT vehicle_id, status, status_version "
            "FROM vehicles WHERE vehicle_id = :v"
        ),
        {"v": vehicle_id},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="vehicle not found")

    # 2. Non-fault transitions: single UPDATE, arithmetic in SQL.
    if new_status != "fault":
        session.execute(
            text(
                "UPDATE vehicles "
                "SET status = :s, status_version = status_version + 1 "
                "WHERE vehicle_id = :v"
            ),
            {"s": new_status, "v": vehicle_id},
        )
        session.commit()
        updated = session.execute(
            text(
                "SELECT status, status_version "
                "FROM vehicles WHERE vehicle_id = :v"
            ),
            {"v": vehicle_id},
        ).one()
        return {
            "vehicle_id": vehicle_id,
            "status": updated.status,
            "status_version": updated.status_version,
        }

    # 3. Fault transition — the atomic multi-statement path.
    #
    # Concurrency: BEGIN IMMEDIATE acquires SQLite's reserved/writer lock at the
    # start of the txn so concurrent fault POSTs serialize. The status re-read
    # inside the lock makes the operation idempotent: writer #N+1 sees fault
    # and short-circuits, so we never create duplicate maintenance records.
    #
    # We use a fresh session (NOT the request-scoped one) so that BEGIN
    # IMMEDIATE is the first statement we issue on the underlying connection,
    # with no implicit transaction already open from prior reads.
    with db.SessionLocal() as fault_session:
        try:
            fault_session.execute(text("BEGIN IMMEDIATE"))

            # a. Re-read current status under the writer lock.
            current = fault_session.execute(
                text(
                    "SELECT status, status_version "
                    "FROM vehicles WHERE vehicle_id = :v"
                ),
                {"v": vehicle_id},
            ).first()
            if current is None:
                # Vanishingly unlikely (we checked above) but be defensive.
                fault_session.rollback()
                raise HTTPException(status_code=404, detail="vehicle not found")

            if current.status == "fault":
                # Idempotent no-op. Commit the (effectively empty) txn so we
                # release the writer lock cleanly.
                fault_session.commit()
                return {
                    "vehicle_id": vehicle_id,
                    "status": current.status,
                    "status_version": current.status_version,
                }

            now = _now_iso()

            # b. Flip status, bump version arithmetically.
            fault_session.execute(
                text(
                    "UPDATE vehicles "
                    "SET status = 'fault', "
                    "    status_version = status_version + 1 "
                    "WHERE vehicle_id = :v"
                ),
                {"v": vehicle_id},
            )

            # c. Cancel whatever active mission exists. rowcount=0 is fine.
            fault_session.execute(
                text(
                    "UPDATE missions "
                    "SET status = 'cancelled', cancelled_at = :t "
                    "WHERE vehicle_id = :v AND status = 'active'"
                ),
                {"v": vehicle_id, "t": now},
            )

            # d. Maintenance record.
            fault_session.execute(
                text(
                    "INSERT INTO maintenance_records "
                    "(vehicle_id, created_at, reason) "
                    "VALUES (:v, :t, 'fault_transition')"
                ),
                {"v": vehicle_id, "t": now},
            )

            # e. Commit, releasing the writer lock.
            fault_session.commit()

            updated = fault_session.execute(
                text(
                    "SELECT status, status_version "
                    "FROM vehicles WHERE vehicle_id = :v"
                ),
                {"v": vehicle_id},
            ).one()
            return {
                "vehicle_id": vehicle_id,
                "status": updated.status,
                "status_version": updated.status_version,
            }
        except HTTPException:
            raise
        except Exception:
            fault_session.rollback()
            raise
