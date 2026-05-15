# Take-Home Project Fullstack Prompt

# **Build a fleet telemetry monitoring service**

You are building a small vertical slice of a fleet monitoring system for 50 autonomous industrial vehicles that emit telemetry at 1 Hz per vehicle. Each telemetry event is a JSON object with: `vehicle_id`, `timestamp`, `lat/lon`, `battery_pct`, `speed_mps`, `status` (one of `idle`, `moving`, `charging`, `fault`), `error_codes` (array of strings), and `zone_entered` **(string zone ID, or** `null` **— non-null only on the event where the vehicle just crossed into a new zone)**.

Example telemetry events:

```json
{
  "vehicle_id": "v-12",
  "timestamp": "...",
  "lat": 37.41,
  "lon": -122.08,
  "battery_pct": 78,
  "speed_mps": 1.2,
  "status": "moving",
  "error_codes": [],
  "zone_entered": null
}
{
  "vehicle_id": "v-12",
  "timestamp": "...",
  "lat": 37.41,
  "lon": -122.08,
  "battery_pct": 77,
  "speed_mps": 1.1,
  "status": "moving",
  "error_codes": [],
  "zone_entered": "charging_bay_1"
}
```

## **Deliver**

1. **A Python backend service** (FastAPI or Django REST — your choice) that:
    1. Accepts telemetry events via a POST endpoint, handling bursts of concurrent writes from multiple vehicles simultaneously
    2. Persists them (SQLite or Postgres — your choice, justify it)
    3. Detects anomalies in real-time (your definition of "anomaly" — justify it in the ADR)
    4. **Zone-traversal counter.** The warehouse floor is partitioned into a fixed set of named zones (~20 zones, defined at startup — provide them as a hardcoded constant). Telemetry events include a `zone_entered` field (a zone ID string or `null`) when a vehicle has just crossed into a new zone. When present, increment that zone's `entry_count` by 1. With 50 vehicles moving simultaneously over overlapping paths, multiple vehicles can enter the same zone at the same instant — your implementation must guarantee every entry is counted. Expose per-zone counts via a `GET /zones/counts` endpoint. Plausible scenario: at shift change or end-of-shift, multiple vehicles converge on the charging zones simultaneously, producing concurrent `zone_entered` events for the same zone in the same second.
    5. Supports a vehicle **status update** operation: when a vehicle transitions to `fault`, its active mission must be atomically cancelled and a maintenance record created. Think carefully about concurrent writes and the correct isolation strategy.
    6. Exposes a REST endpoint to query recent anomalies filtered by vehicle and time range
    7. Exposes an endpoint to fetch the **current aggregate fleet state** (per-status counts across all 50 vehicles) that is safe under concurrent updates
2. **A small React + TypeScript dashboard** that:
    1. Shows a live list of the 50 vehicles with current status + battery
    2. Surfaces the most recent anomaly per vehicle
    3. Polling or websockets — your choice, justify it
    4. Per-zone entry counts, updating live.
3. **A 1-page Architecture Decision Record (ADR)** that answers:
    1. What were the two or three most important decisions you made, and why?
    2. What constraints or requirements were **unclear** in this spec, and what did you assume? (Deliberately — the spec leaves things open.)
    3. What would need to change if scale grew significantly? You define "significantly.”
    4. What did you deliberately leave out, and why?
4. **An AI Interaction Log** — a plain markdown file containing:
    1. Every meaningful prompt you issued to an AI tool
    2. The output you got back (summary is fine — full copy-paste not required)
    3. Corrections or redirections you made when the AI got it wrong
    4. A 3-5 bullet reflection at the end: what the AI was good at, where it failed you, what you had to double-check manually

## Constraints

1. Budget 5-6 hours total. We value the ADR and AI log as much as the code.
2. You are explicitly encouraged to use AI tools (Cursor, Claude Code, Copilot, etc.). The AI log is part of the deliverable — not using AI is not a positive signal.
3. A partial but well-documented submission beats a complete but undocumented one.
4. We will run your code but will not penalize for environment-specific setup issues if the README is clear.
5. Accepts telemetry events via a POST endpoint, handling bursts of concurrent writes from multiple vehicles simultaneously
6. Persists them (SQLite or Postgres — your choice, justify it)
7. Detects anomalies in real-time **(your definition of "anomaly" — justify it in the ADR)**
8. Supports a vehicle **status update** operation: when a vehicle transitions to `fault`, its active mission must be atomically cancelled and a maintenance record created. Think carefully about concurrent writes and the correct isolation strategy.
9. Exposes a REST endpoint to query recent anomalies filtered by vehicle and time range
10. Exposes an endpoint to fetch the **current aggregate fleet state** (per-status counts across all 50 vehicles) that is safe under concurrent updates
11. A list of 20 zones is provided as a hardcoded constant in the repo (see `ZONES` below). You don't need to model zone geometry — assume the vehicle's edge client populates `zone_entered` correctly when it crosses a boundary.
    
    ```python
    ZONES = [
      "inbound_dock_a",
      "inbound_dock_b",
      "receiving_staging",
      "aisle_a",
      "aisle_b",
      "aisle_c",
      "high_bay_1",
      "high_bay_2",
      "bulk_storage",
      "pick_zone_1",
      "pick_zone_2",
      "pack_station",
      "sort_belt",
      "outbound_dock_a",
      "outbound_dock_b",
      "shipping_staging",
      "charging_bay_1",
      "charging_bay_2",
      "charging_bay_3",
      "maintenance_bay",
    ]
    ```
    

**Submit as a single public Git repo link (GitHub or similar) with a README that explains how to run it.**