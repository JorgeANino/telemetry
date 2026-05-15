# Spec Ambiguities

These are points the spec deliberately leaves open. Each must be resolved by the implementer and acknowledged in the ADR's section 2 ("constraints or requirements that were unclear... and what did you assume").

> **Note on draft text below:** The subagent that produced this file proposed Postgres in items #2, #4, #5, #6, and per-object (no batch) ingest in #9. Those proposals are **superseded by `decisions.md`**:
> - DB → **SQLite + WAL** (not Postgres) — see decisions.md §1
> - Fault isolation → **`BEGIN IMMEDIATE` on SQLite** (not `SELECT … FOR UPDATE`) — see decisions.md §1
> - Zone counter → **atomic `UPDATE … SET entry_count = entry_count + 1`** under SQLite's single-writer (the mechanism the agent proposed is right; the engine differs)
> - Aggregate fleet state → **single `GROUP BY` against SQLite's WAL snapshot** (mechanism unchanged; engine differs)
> - Ingest payload → **single OR batch (array)** accepted at `POST /telemetry` (the agent proposed single-only; we accept both because the spec's example shows two events back-to-back and batches are trivial under the same transaction)
>
> The text below is preserved as the raw extraction; ADR section 2 will reflect the locked decisions, not the suggestions here.

## 1. Backend framework choice

- **What's unclear:** "A Python backend service (FastAPI or Django REST — your choice)"
- **The decision space:** FastAPI (async-native, lightweight, fast for I/O-bound bursts) vs. Django REST (batteries-included, ORM + admin + migrations out of the box, heavier).
- **What we should write in the ADR's section 2:** We chose FastAPI because the workload is bursty concurrent writes from 50 vehicles at 1 Hz and benefits from async I/O without needing Django's full stack.

## 2. Database choice

- **What's unclear:** "Persists them (SQLite or Postgres — your choice, justify it)"
- **The decision space:** SQLite (zero-setup, single file, fine for a take-home and 50 vehicles @ 1 Hz, but weaker concurrent-write story) vs. Postgres (true row-level locking, MVCC, strong isolation guarantees that match the fault-transition requirement).
- **What we should write in the ADR's section 2:** We chose Postgres because the spec explicitly requires correct behavior under concurrent writes (zone counters, fault transitions, aggregate fleet state) and Postgres's row-level locking + SERIALIZABLE/READ COMMITTED options make those guarantees straightforward.

## 3. Definition of "anomaly"

- **What's unclear:** "Detects anomalies in real-time (your definition of 'anomaly' — justify it in the ADR)"
- **The decision space:** Threshold-based (battery below X%, speed above Y, presence of any `error_codes`), state-machine-based (illegal status transitions), statistical (z-score over rolling window per vehicle), or any combination. Real-time means evaluated synchronously at ingest vs. via a background worker.
- **What we should write in the ADR's section 2:** We define an anomaly as any of: battery_pct below 15, speed_mps above a safe-floor threshold (e.g. 5 m/s), a non-empty error_codes array, or a transition into `fault`, evaluated synchronously on each POST /telemetry write.

## 4. Isolation strategy for the fault transition

- **What's unclear:** "Think carefully about concurrent writes and the correct isolation strategy" (for fault transition + mission cancel + maintenance record).
- **The decision space:** SELECT ... FOR UPDATE row lock on the vehicle/mission row inside a single transaction; SERIALIZABLE transaction isolation; advisory locks; application-level mutex.
- **What we should write in the ADR's section 2:** We wrap the fault transition in a single DB transaction that takes a row-level FOR UPDATE lock on the vehicle's active mission, cancels it, and inserts a maintenance record, so the operation is atomic and safe against concurrent fault writes.

## 5. Concurrency strategy for the zone counter

- **What's unclear:** The spec demands every concurrent `zone_entered` event be counted but does not prescribe how.
- **The decision space:** Atomic UPDATE ... SET entry_count = entry_count + 1 (relies on row-level locks), SELECT ... FOR UPDATE then UPDATE, INSERT-into-events-table with a COUNT() at read time, Redis INCR.
- **What we should write in the ADR's section 2:** We increment via an atomic `UPDATE zones SET entry_count = entry_count + 1 WHERE id = ?` so concurrent writers serialize on the row lock and no event is lost.

## 6. Concurrency strategy for aggregate fleet state

- **What's unclear:** "Safe under concurrent updates" without specifying mechanism.
- **The decision space:** Compute on read with a single GROUP BY query under READ COMMITTED, maintain a denormalized counters table updated transactionally, cache with periodic refresh.
- **What we should write in the ADR's section 2:** We compute per-status counts on read via a single `SELECT status, COUNT(*) ... GROUP BY status` query, which is consistent under Postgres's default isolation and avoids denormalized-counter drift.

## 7. Polling vs. websockets on the frontend

- **What's unclear:** "Polling or websockets — your choice, justify it"
- **The decision space:** Short-interval polling (simple, stateless, fine for ~50 rows at 1-2 Hz UI refresh) vs. websockets (push, lower latency, more infra/state to manage).
- **What we should write in the ADR's section 2:** We use polling at ~1-2 s intervals because the dashboard has 50 rows and a small zone table, the data is naturally pull-shaped, and websockets would add complexity disproportionate to the 5-6 hour budget.

## 8. Definition of "significantly" for scale

- **What's unclear:** "What would need to change if scale grew significantly? You define 'significantly.'"
- **The decision space:** 10x vehicles (500), 100x vehicles (5000), 1000x vehicles, or higher-frequency telemetry (10 Hz, 100 Hz), or longer retention.
- **What we should write in the ADR's section 2:** We define "significantly" as roughly 100x more vehicles (5,000) or 10x higher telemetry frequency, at which point ingest would move behind a message queue (Kafka/NATS), counters would move to Redis, and the DB would be partitioned by vehicle_id.

## 9. Payload accepts list OR single object

- **What's unclear:** The spec's example block shows two JSON objects back-to-back, suggesting POST /telemetry could plausibly accept a single event or a batch. The spec does not explicitly say which.
- **The decision space:** Accept only a single object, accept only an array, or accept both.
- **What we should write in the ADR's section 2:** We accept a single telemetry object per POST /telemetry call; batch ingest is out of scope for this slice (noted in ADR section 4 as deliberately omitted).

## 10. Anomaly retention / "recent" window

- **What's unclear:** "Query recent anomalies filtered by vehicle and time range" — "recent" is undefined.
- **The decision space:** Last N (e.g. 100) per vehicle, last 24 h, all history with default time-range filter.
- **What we should write in the ADR's section 2:** We store all anomalies but the endpoint defaults to the last 1 hour when no time range is supplied, and callers may pass explicit `from`/`to` query params.

## 11. Mission model

- **What's unclear:** The fault transition refers to an "active mission" but no mission ingest/creation endpoint is specified.
- **The decision space:** Seed missions at startup, infer a mission per vehicle implicitly, or add a minimal missions table with a seed script.
- **What we should write in the ADR's section 2:** We seed one active mission per vehicle at startup so the fault-transition path has something concrete to cancel; a full mission lifecycle API is deliberately out of scope.

## 12. Timestamp semantics

- **What's unclear:** `timestamp` field format is not specified beyond `"..."` in the example.
- **The decision space:** ISO-8601 string, epoch seconds, epoch milliseconds; UTC vs. local.
- **What we should write in the ADR's section 2:** We require ISO-8601 UTC timestamps on incoming telemetry and store them as timestamptz.
