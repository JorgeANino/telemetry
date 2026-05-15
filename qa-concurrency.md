# QA Concurrency Report

**Test file:** `/Users/jorgenino/Documents/telemetry/backend/tests/qa_concurrency.py`

**Backend under test:** `http://127.0.0.1:8765` (live, with pre-existing state)

**Command run:**
```
cd /Users/jorgenino/Documents/telemetry/backend && .venv/bin/python -m pytest tests/qa_concurrency.py -v -s
```

## Full pytest output

```
============================= test session starts ==============================
platform darwin -- Python 3.14.4, pytest-8.4.2, pluggy-1.6.0 -- /Users/jorgenino/Documents/telemetry/backend/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/jorgenino/Documents/telemetry/backend
plugins: anyio-4.13.0
collecting ... collected 3 items

tests/qa_concurrency.py::test_zone_counter_burst_exact 
[Test 1] baseline charging_bay_1 count: 11
[Test 1] HTTP statuses: total=200 non2xx=0
[Test 1] baseline=11 expected=211 actual=211
PASSED
tests/qa_concurrency.py::test_fault_transition_atomicity_live 
[Test 2] pre-state v-20: status=moving
[Test 2] pre DB: vehicles.status=moving status_version=0 cancelled_missions=0 maintenance_records=0
[Test 2] response codes: [200, 200, 200, 200, 200, 200, 200, 200, 200, 200]
[Test 2] post DB: vehicles.status=fault status_version=1 cancelled_missions=1 maintenance_records=1
[Test 2] expected: status=fault status_version=1 cancelled_missions=1 maintenance_records=1
PASSED
tests/qa_concurrency.py::test_fleet_state_consistency_under_writes 
[Test 3] baseline fleet/state={'idle': 0, 'moving': 49, 'charging': 0, 'fault': 1} sum=50
[Test 3] write burst non-2xx count: 0
[Test 3] final fleet/state={'idle': 18, 'moving': 18, 'charging': 14, 'fault': 0} sum=50
[Test 3] snapshots (20 polls):
  poll 00: sum=50 {'idle': 5, 'moving': 39, 'charging': 5, 'fault': 1}
  poll 01: sum=50 {'idle': 13, 'moving': 23, 'charging': 14, 'fault': 0}
  poll 02: sum=50 {'idle': 21, 'moving': 16, 'charging': 13, 'fault': 0}
  poll 03: sum=50 {'idle': 16, 'moving': 18, 'charging': 16, 'fault': 0}
  poll 04: sum=50 {'idle': 18, 'moving': 18, 'charging': 14, 'fault': 0}
  poll 05: sum=50 {'idle': 16, 'moving': 17, 'charging': 17, 'fault': 0}
  poll 06: sum=50 {'idle': 12, 'moving': 19, 'charging': 19, 'fault': 0}
  poll 07: sum=50 {'idle': 17, 'moving': 15, 'charging': 18, 'fault': 0}
  poll 08: sum=50 {'idle': 16, 'moving': 18, 'charging': 16, 'fault': 0}
  poll 09: sum=50 {'idle': 18, 'moving': 16, 'charging': 16, 'fault': 0}
  poll 10: sum=50 {'idle': 16, 'moving': 16, 'charging': 18, 'fault': 0}
  poll 11: sum=50 {'idle': 16, 'moving': 15, 'charging': 19, 'fault': 0}
  poll 12: sum=50 {'idle': 16, 'moving': 17, 'charging': 17, 'fault': 0}
  poll 13: sum=50 {'idle': 14, 'moving': 17, 'charging': 19, 'fault': 0}
  poll 14: sum=50 {'idle': 15, 'moving': 19, 'charging': 16, 'fault': 0}
  poll 15: sum=50 {'idle': 14, 'moving': 19, 'charging': 17, 'fault': 0}
  poll 16: sum=50 {'idle': 21, 'moving': 17, 'charging': 12, 'fault': 0}
  poll 17: sum=50 {'idle': 18, 'moving': 18, 'charging': 14, 'fault': 0}
  poll 18: sum=50 {'idle': 18, 'moving': 18, 'charging': 14, 'fault': 0}
  poll 19: sum=50 {'idle': 18, 'moving': 18, 'charging': 14, 'fault': 0}
PASSED

============================== 3 passed in 1.79s ===============================
```

## Test verdicts

### Test 1 — Zone counter burst (`test_zone_counter_burst_exact`)

**Verdict:** PASS

- Zone: `charging_bay_1`
- Concurrency: 200 POST /telemetry events across `ThreadPoolExecutor(max_workers=50)`, each carrying `zone_entered="charging_bay_1"` with distinct microsecond-offset timestamps and round-robin vehicle ids v-00..v-49.
- Baseline count: **11**
- Expected final: **211** (baseline + 200)
- Actual final: **211**
- HTTP non-2xx count: 0

The zone counter increments are atomic: zero events were lost or double-counted under a 50-thread burst.

### Test 2 — Fault transition atomicity (`test_fault_transition_atomicity_live`)

**Verdict:** PASS

- Target vehicle: `v-20`
- Concurrency: 10 concurrent POST `/vehicles/v-20/status` with `{"new_status":"fault"}` via `ThreadPoolExecutor(max_workers=10)`.
- Pre DB state: `status=moving`, `status_version=0`, `cancelled_missions=0`, `maintenance_records=0`
- All 10 responses returned HTTP 200.
- Post DB state:
  - `vehicles.status` = `fault` (expected `fault`) — match
  - `vehicles.status_version` = `1` (expected `1`) — match (bumped exactly once)
  - `missions` cancelled for v-20 = `1` (expected `1`) — match (seed mission cancelled exactly once)
  - `maintenance_records` for v-20 = `1` (expected `1`) — match (created exactly once)

The fault-transition critical section is properly serialised: only one of the 10 concurrent transitions performed the side effects. The other 9 returned 200 idempotently without duplicating mission cancellations or maintenance rows.

### Test 3 — Fleet state consistency under writes (`test_fleet_state_consistency_under_writes`)

**Verdict:** PASS

- Baseline `/fleet/state`: `{'idle': 0, 'moving': 49, 'charging': 0, 'fault': 1}` (sum = 50)
- Write burst: 1000 POST /telemetry events (50 vehicles × 20 events) cycling status through `['idle','moving','charging']` via `ThreadPoolExecutor(max_workers=20)`.
- 20 polls of `/fleet/state` during burst at 50ms intervals + 1 final poll after burst.
- Every snapshot satisfied:
  - all 4 status keys present (`idle`, `moving`, `charging`, `fault`)
  - all values non-negative `int`
  - sum across all values == `50` (seeded vehicle count)
- Write burst non-2xx count: 0
- Final snapshot: `{'idle': 18, 'moving': 18, 'charging': 14, 'fault': 0}` (sum = 50)

Read-side aggregation remained consistent throughout: no in-flight snapshot showed phantom or missing vehicles. The `/fleet/state` endpoint observes a single consistent point-in-time view of the vehicles table even under sustained concurrent upserts.

## Summary

- **Tests run:** 3
- **PASS:** 3
- **FAIL:** 0
- **P0 count:** 0
- **P1 count:** 0
- **P2 count:** 0

No concurrency bugs surfaced under these workloads. Zone counter increments are atomic, fault transitions exhibit at-most-once side effects under 10-way contention, and `/fleet/state` aggregation is consistent under a 20-thread / 1000-event upsert burst.
