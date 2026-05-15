# Locked Decisions

These are the four top-level technology decisions, locked before code is written. Each has a one-paragraph justification grounded in the spec's constraints (50 vehicles × 1 Hz = ~50 events/s peak, take-home time budget 5–6h, no real-time requirement stated).

---

## 1. Database — SQLite with WAL mode

**Decision:** SQLite, with `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` set at connection open. Single file at `backend/telemetry.db`.

**Why:**
- The spec's load is ~50 writes/s (50 vehicles × 1 Hz) plus a small read fan-out from the dashboard. SQLite in WAL mode comfortably handles thousands of writes/s on a laptop; we are two orders of magnitude under that.
- WAL mode gives us readers-do-not-block-writers and writers-do-not-block-readers semantics, which is exactly what the dashboard polling needs while ingestion is happening.
- SQLite serializes writers to a single transaction at a time. That is a feature, not a bug, for the concurrency hot spots in this spec: the zone counter and the fault transition both become trivially correct under a single writer if we use `UPDATE … SET col = col + 1` arithmetic (not Python read-modify-write) and `BEGIN IMMEDIATE` for the multi-statement fault transition.
- Postgres would add a Docker / connection-pool / dev-loop tax for zero correctness benefit at this load. The ADR will explicitly say "swap to Postgres at the scale-up point" with the trigger condition.
- Zero ops. Graders can `pip install -r requirements.txt && uvicorn …` and have a working DB.

**Trade-off accepted:** single-writer serialization caps theoretical throughput; we explain in the ADR what changes at 100× scale.

---

## 2. Web framework — FastAPI

**Decision:** FastAPI (with Pydantic v2) on Uvicorn, single worker.

**Why:**
- Pydantic validation is free at the door — telemetry events are a fixed schema with mixed nullable fields (`zone_entered`, `error_codes`), exactly the case Pydantic handles cleanly without boilerplate.
- The endpoint surface is tiny (5 endpoints). Django REST Framework's serializer/viewset/router ceremony would be net negative at this surface area.
- Async-capable if we need it later, but we are running sync handlers with sync SQLAlchemy — async + SQLite gives no real concurrency benefit because SQLite serializes writers anyway, and the sync model keeps the transaction-boundary reasoning simpler. This is a deliberate choice, documented inline in code.
- Auto-generated `/docs` OpenAPI is a free win for graders who want to poke the API without reading the README.

**Trade-off accepted:** single uvicorn worker means we cannot horizontally scale within one process. That is fine for this load; the ADR will note that adding workers requires moving off SQLite.

---

## 3. Frontend update strategy — Polling at 2 s

**Decision:** Frontend polls `GET /fleet/state`, `GET /zones/counts`, and `GET /anomalies?limit=20` every 2 seconds via `setInterval`. No WebSocket, no SSE.

**Why:**
- The spec does not assert a real-time latency budget. "Updating live" in the spec means "the dashboard reflects current state," not "sub-second push." 2-second polling meets that bar.
- Three lightweight GETs at 0.5 Hz is ~1.5 requests/s of dashboard load, negligible against the 50 ingestion writes/s. No backpressure risk.
- WebSocket adds: a connection-state machine on the client, a fan-out mechanism on the server (or a pubsub like Redis), reconnection logic, and a separate code path for initial load vs. updates. None of that is in the spec, and all of it is risk inside a 90-minute frontend budget.
- Polling is trivially debuggable — every update is a single HTTP request visible in DevTools.

**Trade-off accepted:** up to 2 s of staleness in the UI. The ADR notes the cutover trigger (sub-second SLA, or per-vehicle live position telemetry) where WS becomes worth it.

---

## 4. Anomaly definition

**Decision:** An anomaly is recorded for an event when **any** of the following holds:

| Code | Trigger |
|---|---|
| `battery_drop` | The vehicle's prior event (any timestamp, but practically within ~60 s at 1 Hz) had `battery_pct` at least 20 percentage points higher than the current event. |
| `overspeed` | `speed_mps > 5` (a fast industrial AGV is typically 1.5–2 m/s; >5 m/s on a warehouse floor is reckless). |
| `error_codes_present` | `error_codes` is non-empty. |
| `status_fault` | `status == "fault"`. |

Each anomaly row records `(vehicle_id, timestamp, code, detail)`. A single event can produce multiple rows if it trips multiple rules.

**Why:**
- All four rules can be evaluated against the inbound event plus at most one cached "last event for this vehicle." No window queries, no cron jobs, no rolling-buffer state. This matters because the spec says "real-time" — i.e. on the write path.
- The four rules cover the three telemetry hazard classes a real fleet ops team cares about: degraded battery (operational), unsafe motion (safety), and system-level fault (maintenance).
- Threshold values (20 pp / 60 s / 5 m/s) are documented constants in `anomaly.py` so a grader can see them and dispute them rather than hunt for magic numbers.

**Trade-off accepted:** we do not do statistical anomaly detection (rolling z-score, isolation forest, etc.). Doing so within a take-home budget would be theatre, not engineering — the spec explicitly says "your definition, justify it." Simple, deterministic, testable rules are the right answer here.

---

## Summary of what is **not** being added (anti-features)

- No auth / API keys
- No rate limiting
- No Kafka / Redis / message bus
- No ORM heavier than needed (SQLAlchemy Core-style usage, no Alembic migrations — `init_db()` creates tables)
- No Docker / Compose
- No CI pipeline
- No observability stack (Prometheus / OTel / Sentry)
- No map / geofencing
- No charts or D3 — entry counts and battery bars are fine as plain HTML
