"""QA concurrency tests run against the LIVE backend at http://127.0.0.1:8765.

These tests are intentionally independent of the pytest fixture stack: they
hit the real server, capture baseline state via HTTP, fire concurrent bursts,
and assert exact deltas.

Run with:
    .venv/bin/python -m pytest tests/qa_concurrency.py -v -s
"""
from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import httpx
import pytest

BASE_URL = "http://127.0.0.1:8765"
DB_PATH = "/Users/jorgenino/Documents/telemetry/backend/telemetry.db"

# Shared client config — generous timeouts because we expect contention.
_TIMEOUT = httpx.Timeout(30.0)


def _get(path: str) -> httpx.Response:
    with httpx.Client(timeout=_TIMEOUT) as c:
        return c.get(f"{BASE_URL}{path}")


def _post(path: str, json: dict) -> httpx.Response:
    with httpx.Client(timeout=_TIMEOUT) as c:
        return c.post(f"{BASE_URL}{path}", json=json)


# ---------------------------------------------------------------------------
# Test 1: Zone counter burst
# ---------------------------------------------------------------------------
def test_zone_counter_burst_exact():
    """200 telemetry events, all with zone_entered=charging_bay_1, fired
    across 50 threads. Final count must equal baseline + 200 exactly.
    """
    zone = "charging_bay_1"
    n_events = 200
    n_workers = 50

    # Baseline
    r = _get("/zones/counts")
    assert r.status_code == 200, f"baseline GET failed: {r.status_code} {r.text}"
    baseline_counts = r.json()["counts"]
    baseline = baseline_counts.get(zone, 0)
    print(f"\n[Test 1] baseline {zone} count: {baseline}")

    base_ts = datetime.now(timezone.utc)

    def _payload(i: int) -> dict:
        vid = f"v-{i % 50:02d}"
        ts = (base_ts + timedelta(microseconds=i)).isoformat()
        return {
            "vehicle_id": vid,
            "timestamp": ts,
            "lat": 1.0,
            "lon": 2.0,
            "battery_pct": 80.0,
            "speed_mps": 0.0,
            "status": "moving",
            "zone_entered": zone,
        }

    def _fire(i: int) -> int:
        resp = _post("/telemetry", _payload(i))
        return resp.status_code

    statuses = []
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(_fire, i) for i in range(n_events)]
        for f in as_completed(futures):
            statuses.append(f.result())

    # All requests should have succeeded (any non-2xx breaks the delta).
    bad = [s for s in statuses if s >= 300]
    print(f"[Test 1] HTTP statuses: total={len(statuses)} non2xx={len(bad)}")
    assert not bad, f"non-2xx responses in burst: {bad[:5]}"

    # Final state
    r2 = _get("/zones/counts")
    assert r2.status_code == 200, f"final GET failed: {r2.status_code} {r2.text}"
    final = r2.json()["counts"].get(zone, 0)
    expected = baseline + n_events

    print(f"[Test 1] baseline={baseline} expected={expected} actual={final}")
    assert final == expected, (
        f"zone counter drift: baseline={baseline} expected={expected} "
        f"actual={final} delta={final - baseline}"
    )


# ---------------------------------------------------------------------------
# Test 2: Fault transition atomicity (live, against v-20)
# ---------------------------------------------------------------------------
def test_fault_transition_atomicity_live():
    """Fire 10 concurrent fault-transition requests at v-20. Backend must
    bump status_version by exactly 1, cancel exactly 1 mission, and create
    exactly 1 maintenance_records row.
    """
    target = "v-20"

    # Sanity: confirm v-20 exists and is not currently in fault. If it is,
    # we'd be testing a no-op transition which still exercises some of the
    # invariants but is weaker. We still proceed and let the assertions
    # judge.
    r = _get("/vehicles")
    assert r.status_code == 200
    vehicles = r.json()
    rec = next((v for v in vehicles if v["vehicle_id"] == target), None)
    assert rec is not None, f"{target} not present in /vehicles"
    pre_status = rec["status"]
    print(f"\n[Test 2] pre-state {target}: status={pre_status}")

    # Read pre DB state for context (read-only)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT status, status_version FROM vehicles WHERE vehicle_id = ?", (target,))
    pre_row = cur.fetchone()
    cur.execute(
        "SELECT COUNT(*) FROM missions WHERE vehicle_id = ? AND status = 'cancelled'",
        (target,),
    )
    pre_cancelled = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM maintenance_records WHERE vehicle_id = ?", (target,)
    )
    pre_maint = cur.fetchone()[0]
    conn.close()
    print(
        f"[Test 2] pre DB: vehicles.status={pre_row[0]} status_version={pre_row[1]} "
        f"cancelled_missions={pre_cancelled} maintenance_records={pre_maint}"
    )

    n_workers = 10

    def _fire(_i: int):
        resp = _post(f"/vehicles/{target}/status", {"new_status": "fault"})
        return resp.status_code, resp.text

    results = []
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(_fire, i) for i in range(n_workers)]
        for f in as_completed(futures):
            results.append(f.result())

    codes = [c for c, _ in results]
    print(f"[Test 2] response codes: {sorted(codes)}")
    assert all(c == 200 for c in codes), f"not all 200: {results}"

    # Verify via direct DB read
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT status, status_version FROM vehicles WHERE vehicle_id = ?", (target,)
    )
    v_row = cur.fetchone()
    cur.execute(
        "SELECT COUNT(*) FROM missions WHERE vehicle_id = ? AND status = 'cancelled'",
        (target,),
    )
    cancelled_count = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM maintenance_records WHERE vehicle_id = ?", (target,)
    )
    maint_count = cur.fetchone()[0]
    conn.close()

    final_status, final_version = v_row
    print(
        f"[Test 2] post DB: vehicles.status={final_status} "
        f"status_version={final_version} cancelled_missions={cancelled_count} "
        f"maintenance_records={maint_count}"
    )
    print(
        f"[Test 2] expected: status=fault status_version=1 "
        f"cancelled_missions=1 maintenance_records=1"
    )

    assert final_status == "fault", f"expected status=fault got {final_status}"
    assert final_version == 1, (
        f"expected status_version=1 got {final_version} (delta from pre={final_version - pre_row[1]})"
    )
    assert cancelled_count == 1, (
        f"expected exactly 1 cancelled mission, got {cancelled_count}"
    )
    assert maint_count == 1, (
        f"expected exactly 1 maintenance record, got {maint_count}"
    )


# ---------------------------------------------------------------------------
# Test 3: Fleet state consistency under writes
# ---------------------------------------------------------------------------
def test_fleet_state_consistency_under_writes():
    """While 1000 telemetry events stream in via 20 threads, the fleet-state
    aggregate must always sum to the seeded vehicle count (50) and contain
    all four status keys with non-negative integer values.
    """
    expected_total = 50  # seeded vehicle count

    # Baseline
    r = _get("/fleet/state")
    assert r.status_code == 200
    baseline = r.json()
    baseline_sum = sum(baseline.values())
    print(f"\n[Test 3] baseline fleet/state={baseline} sum={baseline_sum}")
    assert baseline_sum == expected_total, (
        f"baseline sum {baseline_sum} != seeded vehicle count {expected_total}"
    )
    for key in ("idle", "moving", "charging", "fault"):
        assert key in baseline, f"missing status key {key} in baseline"

    statuses_cycle = ["idle", "moving", "charging"]
    n_events = 1000  # 50 vehicles * 20 events
    base_ts = datetime.now(timezone.utc)

    def _payload(i: int) -> dict:
        vid = f"v-{i % 50:02d}"
        st = statuses_cycle[i % len(statuses_cycle)]
        ts = (base_ts + timedelta(microseconds=i)).isoformat()
        return {
            "vehicle_id": vid,
            "timestamp": ts,
            "lat": 1.0,
            "lon": 2.0,
            "battery_pct": 50.0,
            "speed_mps": 0.0,
            "status": st,
        }

    def _fire(i: int) -> int:
        resp = _post("/telemetry", _payload(i))
        return resp.status_code

    ex = ThreadPoolExecutor(max_workers=20)
    try:
        futures = [ex.submit(_fire, i) for i in range(n_events)]

        snapshots = []
        for poll_i in range(20):
            r = _get("/fleet/state")
            assert r.status_code == 200, f"poll {poll_i} got {r.status_code}"
            snap = r.json()
            snapshots.append(snap)
            # Invariant 1: all 4 status keys present
            for key in ("idle", "moving", "charging", "fault"):
                assert key in snap, f"poll {poll_i}: missing key {key} in {snap}"
            # Invariant 2: non-negative integers
            for k, v in snap.items():
                assert isinstance(v, int), (
                    f"poll {poll_i}: value for {k} is {type(v).__name__}={v}"
                )
                assert v >= 0, f"poll {poll_i}: negative value for {k}: {v}"
            # Invariant 3: sum == 50
            s = sum(snap.values())
            assert s == expected_total, (
                f"poll {poll_i}: sum {s} != {expected_total} snapshot={snap}"
            )
            time.sleep(0.05)

        # Wait for all writes to finish
        bad = []
        for f in as_completed(futures):
            code = f.result()
            if code >= 300:
                bad.append(code)
    finally:
        ex.shutdown(wait=True)

    print(f"[Test 3] write burst non-2xx count: {len(bad)}")
    assert not bad, f"telemetry burst had non-2xx: {bad[:5]}"

    # Final snapshot
    r_final = _get("/fleet/state")
    assert r_final.status_code == 200
    final = r_final.json()
    final_sum = sum(final.values())
    print(f"[Test 3] final fleet/state={final} sum={final_sum}")
    print(f"[Test 3] snapshots (20 polls):")
    for i, s in enumerate(snapshots):
        print(f"  poll {i:02d}: sum={sum(s.values())} {s}")

    for key in ("idle", "moving", "charging", "fault"):
        assert key in final, f"final missing key {key}"
    for k, v in final.items():
        assert isinstance(v, int) and v >= 0, f"final bad value {k}={v}"
    assert final_sum == expected_total, (
        f"final sum {final_sum} != {expected_total} snapshot={final}"
    )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v", "-s"]))
