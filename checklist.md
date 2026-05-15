# Fleet Telemetry Checklist

## Backend endpoints

- [x] Backend is implemented in Python
- [x] Backend uses either FastAPI or Django REST (implementer's choice)
- [x] POST /telemetry endpoint exists to accept telemetry events
- [x] POST /telemetry validates payload shape (vehicle_id, timestamp, lat, lon, battery_pct, speed_mps, status, error_codes, zone_entered)
- [x] POST /telemetry accepts status values of `idle`, `moving`, `charging`, or `fault`
- [x] POST /telemetry accepts `error_codes` as an array of strings
- [x] POST /telemetry accepts `zone_entered` as a string zone ID
- [x] POST /telemetry accepts `zone_entered` as `null`
- [x] GET /zones/counts endpoint exposes per-zone entry counts
- [x] REST endpoint exists to query recent anomalies
- [x] Anomaly query endpoint supports filtering by vehicle
- [x] Anomaly query endpoint supports filtering by time range
- [x] Endpoint exists to fetch current aggregate fleet state (per-status counts across all 50 vehicles)
- [x] Aggregate fleet state endpoint is safe under concurrent updates
- [x] Vehicle status update operation is supported

## Concurrency requirements

- [x] POST /telemetry handles bursts of concurrent writes from multiple vehicles simultaneously
- [x] Zone counter implementation guarantees every entry is counted under concurrent writes
- [x] Concurrent `zone_entered` events for the same zone in the same second all increment the count
- [x] Status update to `fault` uses correct isolation strategy for concurrent writes
- [x] Mission cancellation + maintenance record creation on fault is atomic
- [x] Aggregate fleet state read is safe under concurrent updates

## Persistence

- [x] Telemetry events are persisted
- [x] Persistence uses either SQLite or Postgres (implementer's choice)
- [x] Persistence choice is justified in the ADR

## Anomaly detection

- [x] Anomalies are detected in real-time
- [x] The definition of "anomaly" is chosen by the implementer
- [x] The anomaly definition is justified in the ADR
- [x] Detected anomalies are queryable via the anomalies endpoint

## Zone counter

- [x] A fixed set of named zones is defined at startup
- [x] Zones are provided as a hardcoded constant named `ZONES`
- [x] The zone list contains the 20 zone IDs listed in the spec (inbound_dock_a, inbound_dock_b, receiving_staging, aisle_a, aisle_b, aisle_c, high_bay_1, high_bay_2, bulk_storage, pick_zone_1, pick_zone_2, pack_station, sort_belt, outbound_dock_a, outbound_dock_b, shipping_staging, charging_bay_1, charging_bay_2, charging_bay_3, maintenance_bay)
- [x] Zone geometry is NOT modeled (edge client populates `zone_entered`)
- [x] When `zone_entered` is non-null, that zone's `entry_count` is incremented by 1
- [x] When `zone_entered` is null, no zone count is incremented
- [x] Per-zone counts are exposed via GET /zones/counts

## Status update / fault transition

- [x] A status update operation exists for vehicles
- [x] When a vehicle transitions to `fault`, its active mission is cancelled
- [x] Mission cancellation on fault is atomic
- [x] When a vehicle transitions to `fault`, a maintenance record is created
- [x] Mission cancellation and maintenance-record creation happen together atomically
- [x] Isolation strategy for the fault transition is chosen deliberately

## Frontend views

- [x] Frontend is built with React
- [x] Frontend uses TypeScript
- [x] Frontend shows a live list of the 50 vehicles
- [x] Vehicle list shows current status per vehicle
- [x] Vehicle list shows battery per vehicle
- [x] Frontend surfaces the most recent anomaly per vehicle
- [x] Frontend displays per-zone entry counts
- [x] Per-zone entry counts update live
- [x] Frontend uses either polling or websockets (implementer's choice)
- [x] The polling-vs-websockets choice is justified

## ADR sections

- [x] ADR is a single page (1 page)
- [x] ADR identifies the two or three most important decisions made
- [x] ADR explains why those decisions were made
- [x] ADR lists constraints or requirements that were unclear in the spec
- [x] ADR states the assumptions made for unclear items
- [x] ADR describes what would need to change if scale grew significantly
- [x] ADR defines what "significantly" means for scale growth
- [x] ADR lists what was deliberately left out
- [x] ADR explains why those things were left out

## AI log requirements

- [x] AI Interaction Log is a plain markdown file
- [x] Log records every meaningful prompt issued to an AI tool
- [x] Log records the output received (summary is acceptable)
- [x] Log records corrections or redirections made when the AI got it wrong
- [❌] Log ends with a 3-5 bullet reflection
> note: lands in Phase 5
- [❌] Reflection covers what the AI was good at
> note: lands in Phase 5
- [❌] Reflection covers where the AI failed
> note: lands in Phase 5
- [❌] Reflection covers what had to be double-checked manually
> note: lands in Phase 5

## Submission / repo

- [❌] Submission is a single public Git repo link (GitHub or similar)
> note: lands in Phase 5
- [❌] Repo contains a README
> note: lands in Phase 5
- [❌] README explains how to run the project
> note: lands in Phase 5
- [x] Total time budget is 5-6 hours
- [x] Submission includes the backend code
- [x] Submission includes the frontend code
- [x] Submission includes the ADR
- [x] Submission includes the AI Interaction Log

## Verification summary (run at 2026-05-15T17:10:00Z)

- Total items: 75
- Pass: 68
- Outstanding: 7

### Outstanding items (with reason)
- Log ends with a 3-5 bullet reflection — lands in Phase 5
- Reflection covers what the AI was good at — lands in Phase 5
- Reflection covers where the AI failed — lands in Phase 5
- Reflection covers what had to be double-checked manually — lands in Phase 5
- Submission is a single public Git repo link (GitHub or similar) — lands in Phase 5
- Repo contains a README — lands in Phase 5
- README explains how to run the project — lands in Phase 5
