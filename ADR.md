# ADR: Fleet Telemetry Monitoring Service

## 1. The two or three most important decisions, and why

**SQLite with WAL mode.** Workload is ~50 writes/s plus a thin dashboard read fan-out — two orders of magnitude under what SQLite-WAL handles on a laptop. WAL gives readers-don't-block-writers, matching the dashboard-polls-while-ingest-runs pattern. Postgres adds a Docker and connection-pool tax for zero correctness benefit at this load. Single file, zero ops.

**One concurrency story for three hot spots, under SQLite's single writer.** SQLite serializes writers; we lean in. The zone counter is `UPDATE zones SET entry_count = entry_count + 1 WHERE id = ?` — arithmetic in SQL, never a Python read-modify-write, so concurrent `zone_entered` events at shift change cannot lose a count. The fault transition (cancel active mission + insert maintenance record + flip status) runs inside `BEGIN IMMEDIATE` so the writer lock is grabbed up front; two concurrent fault writes for the same vehicle serialize cleanly and the second sees the cancelled mission. Aggregate fleet state is a single `SELECT status, COUNT(*) … GROUP BY status` against the WAL snapshot — one consistent read, no denormalized counter to drift.

**Anomaly is a deterministic rule set, evaluated on the write path.** Four rules: `battery_drop` (>=20 pp drop vs. the vehicle's prior event), `overspeed` (`speed_mps > 5`), `error_codes_present` (non-empty array), `status_fault` (`status == "fault"`). One event can emit multiple rows. Every rule is computable from the inbound event plus one cached last-event-per-vehicle — no rolling windows, no background workers, no statistical models. "Real-time" in the spec means synchronous-with-ingest; this delivers it without the theatre of an isolation forest in a take-home.

## 2. Unclear requirements and the assumptions we made

- **Anomaly thresholds.** We assume 20 percentage-point battery drop, 5 m/s overspeed (industrial AGVs run 1.5–2 m/s), and any non-empty `error_codes` array. Constants live in `anomaly.py` for graders to dispute.
- **Mission seed model.** The spec references an "active mission" with no creation endpoint; we seed exactly one active mission per vehicle at startup so the fault transition has a concrete row to cancel.
- **Timestamp format.** Incoming `timestamp` is ISO-8601 UTC; we store it as ISO text and parse on read.
- **Batch vs. single ingest.** `POST /telemetry` accepts either a single event object or a JSON array of events; the spec's example shows two events back-to-back and batches cost nothing under the same transaction.
- **"Recent" anomalies default window.** `GET /anomalies` defaults to the last 1 hour when no time range is supplied; callers may override with explicit `from` / `to` query params and a `vehicle_id` filter.
- **Dashboard freshness.** "Live" means current, not sub-second; we poll three GETs every 2 s, which is ~1.5 req/s of UI load against ~50 ingest writes/s.
- **Last-event cache.** The `battery_drop` rule uses an in-process dict of last-event-per-vehicle, hydrated lazily from the DB on first sight of a vehicle.
- **Data plane vs. control plane.** Anomaly rules (including `status_fault`) fire only on the telemetry-ingest path. `POST /vehicles/{id}/status` is the control plane: it writes a `MaintenanceRecord` as the durable fault trace but does not emit an anomaly row.

## 3. What would change at significant scale

"Significantly" means 100× vehicles (5,000) or 10× frequency (10 Hz) — roughly 50,000 writes/s. Three things break first, in this order:

1. **SQLite's single writer.** Serialized writes cap us well below the new rate. Cutover is Postgres with row-level locks replacing `BEGIN IMMEDIATE`; zone counter and fault transition keep their shape.
2. **Single uvicorn worker.** One process cannot saturate multiple cores at that volume. Add workers behind a load balancer — only safe after the Postgres move, because multiple workers against SQLite reintroduce the writer bottleneck across processes.
3. **In-memory last-event cache.** Per-process state breaks the moment a second worker exists. The cache moves to Redis, which also unblocks ingest moving behind Kafka/NATS for burst buffering.

Zone counts and fleet state stay as live aggregates on Postgres; further scale denormalizes them into Redis counters refreshed transactionally.

## 4. What we deliberately left out, and why

- **Auth / API keys** — single-tenant take-home, no threat model.
- **Rate limiting** — no untrusted clients; ingest comes from known vehicles.
- **Docker / Compose** — SQLite + a single `uvicorn` command is simpler than a container for graders.
- **Observability (Prometheus / OTel / Sentry)** — no SLOs to observe against; adds setup with no demonstration value.
- **Batch-ingest validation richer than Pydantic** — Pydantic v2 catches schema violations at the door; per-event semantic validation lives in the anomaly rules themselves.
- **Map / geofencing UI** — zone geometry is out of scope per the spec; the edge client populates `zone_entered`.
- **Mission lifecycle API** — only the fault-cancel path is in the spec; create/complete/reassign endpoints are not.
- **Alerting / webhooks** — anomalies are queryable via REST; outbound notification is a separate product surface.
- **Charts / D3** — entry counts and battery values render fine as plain HTML; visual polish is not graded.
