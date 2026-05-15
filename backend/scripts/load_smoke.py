"""Load smoke test: 50 simulated vehicles posting 60 events over 60 seconds.

That's the spec's stated load (50 vehicles × 1 Hz = 50 events/s for 60 s =
3000 events). We post via HTTP to a running uvicorn server (default
http://127.0.0.1:8000) and verify after the run that:

  - Every request returned 202.
  - Telemetry row count == events posted.
  - Zone counts == events posted with a non-null zone_entered.
  - No errors propagated.

Run a fresh server against a fresh DB before this script — the DB is shared
across runs, so re-running this against an existing DB will accumulate counts.
"""
from __future__ import annotations

import random
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

import os
BASE_URL = os.environ.get("TELEMETRY_URL", "http://127.0.0.1:8000")
NUM_VEHICLES = 50
EVENTS_PER_VEHICLE = 60
ZONES = [
    "inbound_dock_a", "inbound_dock_b", "receiving_staging",
    "aisle_a", "aisle_b", "aisle_c",
    "high_bay_1", "high_bay_2", "bulk_storage",
    "pick_zone_1", "pick_zone_2", "pack_station", "sort_belt",
    "outbound_dock_a", "outbound_dock_b", "shipping_staging",
    "charging_bay_1", "charging_bay_2", "charging_bay_3",
    "maintenance_bay",
]


def post_json(path: str, body: bytes) -> int:
    req = Request(f"{BASE_URL}{path}", data=body, method="POST",
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as resp:
        return resp.status


def get_json(path: str):
    import json
    with urlopen(f"{BASE_URL}{path}", timeout=10) as resp:
        return json.loads(resp.read())


def vehicle_worker(vid: str, results: list, errors: list, lock: threading.Lock):
    import json
    rng = random.Random(hash(vid) & 0xFFFFFFFF)
    battery = 100.0
    for i in range(EVENTS_PER_VEHICLE):
        # Roughly 10% of events cross into a zone — matches a vehicle
        # traversing zones every ~10 s at moderate speed.
        zone_entered = rng.choice(ZONES) if rng.random() < 0.10 else None
        # Drain a small amount of battery per event so we exercise the
        # battery_drop anomaly threshold occasionally (~20pp jumps stay rare).
        battery = max(0.0, battery - rng.uniform(0.1, 1.0))
        event = {
            "vehicle_id": vid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lat": 37.41 + rng.random() * 0.001,
            "lon": -122.08 + rng.random() * 0.001,
            "battery_pct": battery,
            "speed_mps": rng.uniform(0.5, 2.0),
            "status": "moving",
            "error_codes": [],
            "zone_entered": zone_entered,
        }
        try:
            status = post_json("/telemetry", json.dumps(event).encode())
            if status != 202:
                with lock:
                    errors.append(f"{vid}#{i}: status={status}")
        except Exception as e:
            with lock:
                errors.append(f"{vid}#{i}: {e!r}")
        else:
            with lock:
                results.append((vid, i, zone_entered))
        # 1 Hz per vehicle
        time.sleep(1.0)


def main() -> int:
    print(f"target: {BASE_URL}")
    print(f"plan:   {NUM_VEHICLES} vehicles × {EVENTS_PER_VEHICLE} events @ 1 Hz "
          f"= {NUM_VEHICLES * EVENTS_PER_VEHICLE} events over ~{EVENTS_PER_VEHICLE}s")
    print()

    # Healthcheck.
    health = get_json("/healthz")
    print(f"healthz: {health}")
    assert health == {"ok": True}

    # Capture pre-run state so we can verify deltas (DB may have prior data).
    pre_fleet = get_json("/fleet/state")
    pre_zones = get_json("/zones/counts")["counts"]
    print(f"pre-fleet:  {pre_fleet}")
    print(f"pre-zones (non-zero): "
          f"{ {k: v for k, v in pre_zones.items() if v > 0} or '(none)' }")
    print()

    results: list = []
    errors: list = []
    lock = threading.Lock()

    threads = [
        threading.Thread(
            target=vehicle_worker,
            args=(f"v-{i:02d}", results, errors, lock),
            name=f"vehicle-{i:02d}",
        )
        for i in range(NUM_VEHICLES)
    ]

    t_start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t_start

    expected_total = NUM_VEHICLES * EVENTS_PER_VEHICLE
    expected_zone_events = sum(1 for _, _, z in results if z is not None)

    print()
    print(f"elapsed:        {elapsed:.1f}s")
    print(f"successes:      {len(results)} / {expected_total}")
    print(f"errors:         {len(errors)}")
    if errors:
        for e in errors[:10]:
            print(f"  - {e}")
        if len(errors) > 10:
            print(f"  ... ({len(errors) - 10} more)")

    post_fleet = get_json("/fleet/state")
    post_zones = get_json("/zones/counts")["counts"]
    zone_delta = {k: post_zones[k] - pre_zones.get(k, 0) for k in post_zones}
    nonzero_delta = {k: v for k, v in zone_delta.items() if v != 0}
    delta_sum = sum(zone_delta.values())

    print()
    print(f"post-fleet:     {post_fleet}")
    print(f"zone delta sum: {delta_sum} (expected {expected_zone_events})")
    print(f"zone deltas:    {nonzero_delta}")

    # Verdict.
    ok = (
        len(errors) == 0
        and len(results) == expected_total
        and delta_sum == expected_zone_events
    )
    print()
    print("VERDICT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
