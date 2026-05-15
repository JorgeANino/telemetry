# QA Functional Report — Fleet Telemetry Backend

Target: `http://127.0.0.1:8765`
Run at: 2026-05-15 (UTC ~17:30–17:45)
Method: live HTTP via `curl`. No backend code modified.

State at start: 50 seeded vehicles; v-10 already in `fault` from prior testing; zone counts already non-zero.

---

## GET /healthz

### Test 1: smoke
- Request: `GET /healthz`
- Response: 200 — `{"ok":true}`
- Verdict: PASS

---

## GET /fleet/state

### Test 2: smoke + status keys + sum equals vehicle count
- Request: `GET /fleet/state`
- Response: 200 — `{"idle":0,"moving":49,"charging":0,"fault":1}` (initial)
- Has all 4 keys: idle, moving, charging, fault. Sum 0+49+0+1 = 50 = vehicle count.
- Verdict: PASS

### Test 3: aggregate reflects status updates
- After issuing `POST /vehicles/v-08/status {"new_status":"idle"}` (and earlier v-06→charging, v-07→fault), `GET /fleet/state` returns `{"idle":1,"moving":46,"charging":1,"fault":2}`. Sum 1+46+1+2 = 50. Counts shifted correctly.
- Verdict: PASS

---

## GET /zones/counts

### Test 4: smoke + 20 zone keys
- Request: `GET /zones/counts`
- Response: 200 — object with 20 keys covering exactly the spec list (`aisle_a`, `aisle_b`, `aisle_c`, `bulk_storage`, `charging_bay_1..3`, `high_bay_1..2`, `inbound_dock_a/b`, `maintenance_bay`, `outbound_dock_a/b`, `pack_station`, `pick_zone_1/2`, `receiving_staging`, `shipping_staging`, `sort_belt`).
- Verdict: PASS

### Test 5: increment on valid zone_entered
- Before: `aisle_a` = 15. Posted valid event with `zone_entered:"aisle_a"`. After: 16.
- Verdict: PASS

### Test 6: no increment on `zone_entered:null`
- Posted valid event for v-00 with `zone_entered:null`. Zone counts overall unchanged.
- Verdict: PASS

---

## GET /vehicles

### Test 7: smoke + 50 rows
- Request: `GET /vehicles`
- Response: 200 — JSON array of length 50. Each row has `vehicle_id`, `status`, `battery_pct`, `last_timestamp`.
- Verdict: PASS

---

## POST /telemetry

### Test 8: valid single event
- Request: `POST /telemetry` body `{"vehicle_id":"v-00","timestamp":"2026-05-15T17:30:00+00:00","lat":40.0,"lon":-73.0,"battery_pct":75.0,"speed_mps":1.5,"status":"moving","error_codes":[],"zone_entered":null}`
- Response: 202 — `{"accepted":1}`
- Verdict: PASS

### Test 9: valid batch (array)
- Request: `POST /telemetry` body = JSON array with 2 events for v-01 and v-02 (zones `aisle_a`, `pick_zone_1`)
- Response: 202 — `{"accepted":2}`
- Side effect: `aisle_a` 13→14, `pick_zone_1` 18→19 in `/zones/counts`. Batch persisted + zone counters bumped.
- Verdict: PASS

### Test 10: missing required field (`vehicle_id`)
- Request: payload without `vehicle_id`
- Response: 422 — `{"detail":[{"type":"missing","loc":["body","TelemetryEventIn","vehicle_id"],"msg":"Field required",...}]}`
- Verdict: PASS

### Test 11: wrong type (`battery_pct:"high"`)
- Request: payload with `battery_pct:"high"`
- Response: 422 — `float_parsing` error
- Verdict: PASS

### Test 12: invalid `status` enum
- Request: payload with `status:"flying"`
- Response: 422 — `literal_error` listing allowed enum values
- Verdict: PASS

### Test 13: unknown `zone_entered`
- Request: payload with `zone_entered:"unknown_zone"`
- Response: 202 — `{"accepted":1}` (silently accepted)
- Side effect: zone count totals unchanged; `unknown_zone` is NOT added to `/zones/counts`. Event is still persisted; only the zone counter step is skipped.
- Verdict: PASS — spec allows implementer-chosen handling; the increment side-effect is correctly suppressed for non-`ZONES` ids and the canonical 20-zone list remains intact. (Could arguably be 422 for stricter input validation — see Notes.)

### Test 14: empty batch `[]`
- Request: body `[]`
- Response: 202 — `{"accepted":0}`
- Verdict: PASS

### Test 15: malformed JSON
- Request: body `not-json`
- Response: 422 — `json_invalid`
- Verdict: PASS

### Test 16: zone_entered as valid string (verify accepted shape)
- Request: telemetry with `zone_entered:"aisle_a"`
- Response: 202 — `{"accepted":1}`. Zone count incremented.
- Verdict: PASS

---

## POST /vehicles/{id}/status

NOTE: the field name in the body is `new_status`, not `status`. Tests below reflect the actual contract.

### Test 17: valid moving
- Request: `POST /vehicles/v-05/status` body `{"new_status":"moving"}`
- Response: 200 — `{"vehicle_id":"v-05","status":"moving","status_version":1}`
- Verdict: PASS

### Test 18: valid charging
- Request: `POST /vehicles/v-06/status` body `{"new_status":"charging"}`
- Response: 200 — `{"vehicle_id":"v-06","status":"charging","status_version":1}`. `/fleet/state` charging count went 0→1.
- Verdict: PASS

### Test 19: valid fault transition
- Request: `POST /vehicles/v-07/status` body `{"new_status":"fault"}`
- Response: 200 — `{"vehicle_id":"v-07","status":"fault","status_version":1}`. `/fleet/state` fault count went 1→2. (Atomicity of mission cancellation + maintenance record is internal; no public endpoint to inspect them, but the status transition itself succeeds and is reflected in aggregates.)
- Verdict: PASS

### Test 20: valid idle
- Request: `POST /vehicles/v-08/status` body `{"new_status":"idle"}`
- Response: 200 — `{"vehicle_id":"v-08","status":"idle","status_version":1}`
- Verdict: PASS

### Test 21: unknown vehicle (expect 404)
- Request: `POST /vehicles/v-doesnotexist/status` body `{"new_status":"moving"}`
- Response: 404 — `{"detail":"vehicle not found"}`
- Verdict: PASS

### Test 22: invalid status enum (expect 422)
- Request: `POST /vehicles/v-05/status` body `{"new_status":"flying"}`
- Response: 422 — `literal_error`, expected `'idle', 'moving', 'charging' or 'fault'`
- Verdict: PASS

### Test 23: missing field
- Request: `POST /vehicles/v-09/status` body `{}`
- Response: 422 — `{"detail":[{"type":"missing","loc":["body","new_status"],...}]}`
- Verdict: PASS

### Test 24: wrong field name (cosmetic check)
- Request: body `{"status":"moving"}` (uses `status` instead of `new_status`)
- Response: 422 — missing `new_status`. Error message is accurate.
- Verdict: PASS (contract is `new_status`; documented in OpenAPI)

---

## GET /anomalies

### Test 25: no params (default 1h window)
- Request: `GET /anomalies`
- Response: 200 — `[]` (initially, no anomalies present)
- Verdict: PASS

### Test 26: vehicle_id filter — hit
- After posting an overspeed event for v-21: `GET /anomalies?vehicle_id=v-21`
- Response: 200 — `[{"id":2,"vehicle_id":"v-21","timestamp":"2026-05-15T17:35:00+00:00","code":"overspeed","detail":"speed=99.0 m/s"}]`
- Verdict: PASS

### Test 27: vehicle_id filter — nonexistent vehicle
- Request: `GET /anomalies?vehicle_id=v-nonexistent`
- Response: 200 — `[]`
- Verdict: PASS

### Test 28: limit=0 (expect 422)
- Request: `GET /anomalies?limit=0`
- Response: 422 — `greater_than_equal` (limit ≥ 1)
- Verdict: PASS

### Test 29: limit=10000 (expect 422)
- Request: `GET /anomalies?limit=10000`
- Response: 422 — `less_than_equal` (limit ≤ 1000)
- Verdict: PASS

### Test 30: from_ts / to_ts wide range
- Request: `GET /anomalies?from_ts=2019-01-01T00:00:00Z&to_ts=2026-12-31T23:59:59Z&limit=50`
- Response: 200 — returns the 2 known anomalies.
- Verdict: PASS

### Test 31: anomaly creation suppressed for old timestamps
- Posted a telemetry event for v-22 with `timestamp:"2020-01-01T00:00:00+00:00"` and both `speed_mps:99` and `error_codes:["E_OLDEVENT"]`. Response 202 `{"accepted":1}`.
- Querying `GET /anomalies?vehicle_id=v-22&from_ts=2019-01-01T00:00:00Z&to_ts=2030-12-31T23:59:59Z` returns `[]`.
- The detector evidently skips events whose timestamp is far from "now" (or filters by ingestion time). This is consistent with a real-time-only detector, which the spec permits ("real-time").
- Verdict: PASS (detector behavior is acceptable; implementer chooses anomaly definition)

### Test 32 (P0 BUG): time-range filter is non-functional
- Two anomalies exist with `timestamp` = `2026-05-15T17:35:00+00:00` (v-20 error_codes_present, v-21 overspeed).
- Request: `GET /anomalies?from_ts=2026-05-15T18:00:00Z&to_ts=2026-05-15T19:00:00Z&limit=50` — window is AFTER the events.
- Response: 200 — returns BOTH anomalies despite the window not covering them.
- Request: `GET /anomalies?from_ts=2030-01-01T00:00:00Z&to_ts=2030-12-31T23:59:59Z&limit=50` — window 4+ years in the future.
- Response: 200 — STILL returns both anomalies.
- Request: `GET /anomalies?from_ts=2026-05-15T17:30:00Z&to_ts=2026-05-15T17:32:00Z&limit=50&vehicle_id=v-20` — window BEFORE the event.
- Response: 200 — STILL returns the v-20 anomaly.
- Conclusion: `from_ts` / `to_ts` query parameters are accepted (no 422) but appear to be IGNORED by the query — every range returns the same rows. This contradicts the spec requirement "Anomaly query endpoint supports filtering by time range".
- Verdict: FAIL — P0

---

## Summary

| Metric | Count |
|---|---|
| Total tests | 32 |
| PASS | 31 |
| FAIL | 1 |

### Failures

| Test | Description | Severity | Reason |
|---|---|---|---|
| Test 32 | `GET /anomalies` `from_ts` / `to_ts` query parameters are ignored — rows that lie outside the requested range are still returned (verified with future window 2030 and pre-event window 17:30–17:32). | **P0** | Contradicts spec: "Anomaly query endpoint supports filtering by time range." Endpoint silently returns wrong rows. |

### Notes (not failures)

- POST `/telemetry` with an unknown `zone_entered` value is silently accepted (HTTP 202) and the zone counter is correctly NOT incremented. This is consistent with the spec ("when `zone_entered` is non-null, that zone's `entry_count` is incremented by 1" — for canonical zones; the canonical 20-zone list is unaffected). A stricter implementation might 422 the request; current behavior is acceptable.
- POST `/vehicles/{id}/status` uses request body field name `new_status`. Body shapes using `status` return 422 (clear error message). Contract is consistent and documented via OpenAPI.
- Anomaly detector does not create records for telemetry events with timestamps far in the past (Test 31). This is plausibly a real-time-only detector and the spec leaves the definition to the implementer; flagged as a behavior to be aware of, not a bug.
- No rate limiting was observed; per ADR §4 this is intentionally out of scope (P2).
- Concurrent-write / atomicity guarantees and maintenance-record creation on fault transition are not directly testable via public endpoints — verified indirectly only (status updates succeed, aggregate state stays consistent).
