# Demo Script — Fleet Telemetry Take-Home

**Target length:** 2:30 (150 s) silent video, on-screen overlays only.
**Author:** demo-scriptwriter agent. The recorder agent (Playwright-based) consumes this document and produces `demo/raw/*.webm`, then ffmpeg post-processes to `demo/demo.mp4`.
**Source of truth:** this file. If anything here conflicts with prior briefs, this wins.

---

## Section 1 — Pre-recording setup checklist

Before invoking the recorder, verify each of the following. Every command is copy-pasteable.

- **Backend reachable on `:8765`**
  - `curl -s http://127.0.0.1:8765/healthz` must return `{"ok":true}`.
- **Frontend reachable on `:5173`**
  - `curl -sI http://127.0.0.1:5173 | head -1` must return `HTTP/1.1 200 OK`.
- **DB has anomalies so the AnomalyFeed is non-empty**
  - `sqlite3 /Users/jorgenino/Documents/telemetry/backend/telemetry.db "SELECT COUNT(*) FROM anomalies;"` must return ≥ 20. Current snapshot: ~54. No action needed unless DB was wiped.
- **Target vehicle for fault beat is NOT already in fault**
  - `curl -s http://127.0.0.1:8765/vehicles | python3 -c "import sys, json; print([v for v in json.load(sys.stdin) if v['vehicle_id']=='v-33'])"`
  - Expected: `status` is anything except `fault`. As of script authoring, v-33 is `charging`. The fault transition is valid from any non-fault status — the overlay simply states the current pre-state read at runtime, not a hardcoded "moving".
- **v-33 has zero maintenance records pre-recording**
  - `sqlite3 /Users/jorgenino/Documents/telemetry/backend/telemetry.db "SELECT COUNT(*) FROM maintenance_records WHERE vehicle_id='v-33';"` must return `0`. If it's not zero, pick a different vehicle and update the constant `TARGET_VEHICLE = "v-33"` at the top of the recorder script.
- **`data-testid` additions are in place in `frontend/src/App.tsx` and the Vite dev server has hot-reloaded** (see Section 2). Verify by curling the page HTML and grepping for `data-testid="last-updated"`.
- **`demo/raw/` directory exists** (`mkdir -p /Users/jorgenino/Documents/telemetry/demo/raw`).
- **`ffmpeg` is on PATH** (`ffmpeg -version | head -1`).
- **Browser fonts render consistently** — Playwright headless Chromium uses bundled fonts; the recorder must run headless (not headed) to keep the output deterministic across machines.

**Note on dashboard reset between takes:** the dashboard reads live DB state. There is no "reset" — each take leaves zone counts higher and v-33 stuck in `fault`. Between takes, re-pick a fresh vehicle and don't try to roll back zone counters. Prefer a single clean take.

---

## Section 2 — `data-testid` additions required in `frontend/src/App.tsx`

The recorder needs reliable selectors that survive Tailwind class churn. Add the following five attributes. **Do not** add any others — keep the diff small.

| # | `data-testid` | Element | Where in App.tsx | Why |
|---|---|---|---|---|
| 1 | `last-updated` | The `<span>` showing `formatClock(lastUpdated)` | Inside the page `<header>`, line ~372 (`<span className="font-mono tabular-nums …">{lastUpdated ? formatClock(lastUpdated) : '—'}</span>`) | Beat 1 overlay points at this so viewers see the polling clock advance. |
| 2 | `zone-card-{zone_id}` | Each zone card `<div>` | Inside the `zones.map((z) => <div key={z} …>)` block in `<ZoneCounts />` (~line 279) — set `data-testid={\`zone-card-${z}\`}` | Beat 3 needs to highlight `charging_bay_1` specifically and read its count delta. |
| 3 | `zone-count-{zone_id}` | The number-display `<div>` inside the card (the `text-xl font-semibold` span) (~line 288) | Set `data-testid={\`zone-count-${z}\`}` | Lets the recorder `page.locator(...).text_content()` to read the count before and after the burst without scraping the whole card. |
| 4 | `vehicle-row-{vehicle_id}` | Each `<tr>` in `<VehicleList />` (~line 173) | Set `data-testid={\`vehicle-row-${v.vehicle_id}\`}` | Beat 4 highlights v-33's row and waits for its status text to flip. |
| 5 | `vehicle-status-{vehicle_id}` | The `<span className="text-slate-700">{v.status}</span>` (~line 188) | Set `data-testid={\`vehicle-status-${v.vehicle_id}\`}` | The status word is what the recorder polls to assert the flip is visible, not just present in the DOM. |

Five additions total. All are string-template attributes inside existing map loops — no structural change.

---

## Section 3 — Beat-by-beat shot list

Total = **150 s**. Polling cadence is 2 s, so every "wait for visible change" beat uses ≥ 3 s dwell (one tick + safety margin).

| Time | Duration | What's on screen | Overlay text | Backend actions in parallel |
|---|---|---|---|---|
| **0:00–0:08** | 8 s | Static title card. Full-page dark overlay (`rgba(15,23,42,0.95)`) over the dashboard. Centered title + subtitle. | **Title:** "Fleet Telemetry" / **Subtitle:** "50 vehicles · 1 Hz · concurrent-safe ingest" | None. |
| **0:08–0:16** | 8 s | Title overlay fades; dashboard visible at rest. Arrow + border highlight on the **Vehicles** panel. | "Live vehicle list — status, battery, latest anomaly" (top-center) | None. |
| **0:16–0:23** | 7 s | Highlight moves to the **Zone entries** panel. | "Zone entry counters — 20 zones, incremented on `zone_entered`" (top-center) | None. |
| **0:23–0:30** | 7 s | Highlight moves to the **Recent anomalies** panel + the `last-updated` span. | "Anomaly feed + 2 s poll clock" (top-center) | None. |
| **0:30–0:50** | 20 s | Run a lightweight 1 Hz simulator in a background thread (50 vehicles, ~10 events each at 1 Hz). Status dots and battery bars tick. | "Live ingestion: 50 vehicles @ 1 Hz" (top-center) | `start_ambient_simulator()` — see Section 4. Runs in a daemon thread for the rest of the recording; the recorder calls `stop_ambient_simulator()` in the final cleanup. |
| **0:50–0:55** | 5 s | Highlight the `charging_bay_1` card. Read its current count via `zone-count-charging_bay_1`. | "charging_bay_1 count: {BEFORE}" (bottom-center) | `before = zone_count("charging_bay_1")` (HTTP GET, not a burst) |
| **0:55–1:05** | 10 s | Burst phase. Overlay shows the action being fired. The card is still highlighted; UI hasn't refreshed yet. | "Firing 200 concurrent POSTs → /telemetry with zone_entered=charging_bay_1" (top-center) | `fire_zone_burst(count=200, zone_id="charging_bay_1")`. Returns once all 200 futures complete. |
| **1:05–1:15** | 10 s | Wait one full poll tick (3 s minimum, here 10 s for visual confirmation), then read post-count via API + zone-count locator. The card animates blue (existing `changed` highlight). | "Expected delta: +200    Actual delta: +{ACTUAL} ✓" (bottom-center). `{ACTUAL}` is `after - before`. If not 200, the overlay reads "{ACTUAL} ✗" and the recorder still proceeds — the discrepancy is the demo. | None (just wait). |
| **1:15–1:20** | 5 s | Clear zone overlays. Scroll the vehicles table to v-33's row. Highlight the row + read its current status via `vehicle-status-v-33`. | "v-33 status: {PRE_STATUS}    maintenance_records: 0" (bottom-center). `{PRE_STATUS}` is read at runtime — usually `charging` or `moving`. | `pre_status = vehicle_status("v-33"); pre_maint = db_count("SELECT COUNT(*) FROM maintenance_records WHERE vehicle_id='v-33'")`. |
| **1:20–1:30** | 10 s | Burst phase 2. v-33 row still highlighted. | "10 concurrent POST → /vehicles/v-33/status {new_status: fault}" (top-center) | `fire_fault_burst("v-33", count=10)`. |
| **1:30–1:45** | 15 s | Wait one+ poll tick. The status dot turns red, the word changes to `fault`. Subprocess SQL is fired during the wait. | "v-33 status: fault ✓    maintenance_records: 1 ✓" (bottom-center). Two checkmarks — exactly one record despite 10 concurrent writers. | `post_maint = db_count("SELECT COUNT(*) FROM maintenance_records WHERE vehicle_id='v-33'")`. Assert `post_maint - pre_maint == 1`. |
| **1:45–2:00** | 15 s | Clear vehicle overlays. Highlight the **Recent anomalies** panel. Then overlay a JSON snippet of `GET /fleet/state` output (curled via subprocess) at the bottom. | Top-center: "Anomaly feed: queryable via GET /anomalies?vehicle_id&from&to". Bottom-center: pre-formatted JSON `{idle: N, moving: N, charging: N, fault: N}` from `curl -s http://127.0.0.1:8765/fleet/state`. | `fleet = http_get_json("/fleet/state")`. |
| **2:00–2:10** | 10 s | Brief look at the AnomalyFeed entries themselves (no extra overlay, just dwell so the viewer can read a couple of codes). | (no overlay) | None. |
| **2:10–2:30** | 20 s | End card. Full-page dark overlay back on. Centered text, multi-line. | Line 1: "Backend — FastAPI + SQLite WAL · BEGIN IMMEDIATE on fault" / Line 2: "Frontend — React + TS · 2 s polling" / Line 3: "ADR · AI log · README in repo" | `stop_ambient_simulator()` called here so the final video doesn't trail off mid-burst. |

### Playwright pseudo-code for the key beats

```python
# Beat 3 — zone burst
clear_overlays(page)
highlight_element(page, '[data-testid="zone-card-charging_bay_1"]', color="yellow")
before = int(page.locator('[data-testid="zone-count-charging_bay_1"]').text_content())
inject_overlay(page, f"charging_bay_1 count: {before}", anchor="bottom")
page.wait_for_timeout(2000)

inject_overlay(page, "Firing 200 concurrent POSTs → /telemetry with zone_entered=charging_bay_1", anchor="top")
fire_zone_burst(count=200, zone_id="charging_bay_1")
page.wait_for_timeout(10000)  # one+ poll cycle, with comfortable margin

after = int(page.locator('[data-testid="zone-count-charging_bay_1"]').text_content())
delta = after - before
mark = "✓" if delta == 200 else "✗"
clear_overlays(page)
highlight_element(page, '[data-testid="zone-card-charging_bay_1"]', color="yellow")
inject_overlay(page, f"Expected delta: +200    Actual delta: +{delta} {mark}", anchor="bottom")
page.wait_for_timeout(5000)
```

```python
# Beat 4 — fault transition
clear_overlays(page)
TARGET = "v-33"
page.locator(f'[data-testid="vehicle-row-{TARGET}"]').scroll_into_view_if_needed()
highlight_element(page, f'[data-testid="vehicle-row-{TARGET}"]', color="yellow")
pre_status = page.locator(f'[data-testid="vehicle-status-{TARGET}"]').text_content().strip()
pre_maint = db_count(f"SELECT COUNT(*) FROM maintenance_records WHERE vehicle_id='{TARGET}'")
inject_overlay(page, f"{TARGET} status: {pre_status}    maintenance_records: {pre_maint}", anchor="bottom")
page.wait_for_timeout(2000)

inject_overlay(page, f"10 concurrent POST → /vehicles/{TARGET}/status {{new_status: fault}}", anchor="top")
fire_fault_burst(TARGET, count=10)
page.wait_for_timeout(10000)

post_status = page.locator(f'[data-testid="vehicle-status-{TARGET}"]').text_content().strip()
post_maint = db_count(f"SELECT COUNT(*) FROM maintenance_records WHERE vehicle_id='{TARGET}'")
delta_maint = post_maint - pre_maint
mark_status = "✓" if post_status == "fault" else "✗"
mark_maint = "✓" if delta_maint == 1 else "✗"
clear_overlays(page)
highlight_element(page, f'[data-testid="vehicle-row-{TARGET}"]', color="yellow")
inject_overlay(
    page,
    f"{TARGET} status: {post_status} {mark_status}    maintenance_records: {post_maint} {mark_maint}",
    anchor="bottom",
)
page.wait_for_timeout(5000)
```

### Dwell-time rationale

The two assertion beats (Beat 3 post and Beat 4 post) each use **10 s of post-burst dwell** rather than the bare minimum 3 s. The frontend polls every 2 s and may have just polled when the burst started, so worst-case the next refresh is 4 s away; 10 s guarantees at least two refreshes and gives the viewer time to read the overlay. Total budget remains 2:30.

---

## Section 4 — Helper code snippets

These are the building blocks the recorder script must include verbatim (or a faithful equivalent). Keep all of them in one module, e.g. `demo/recorder_helpers.py`, and import them from the main `demo/record.py`.

```python
# demo/recorder_helpers.py
from __future__ import annotations

import json
import subprocess
import threading
import time
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

import urllib.request

BACKEND = "http://127.0.0.1:8765"
DB_PATH = "/Users/jorgenino/Documents/telemetry/backend/telemetry.db"


# ---------------------------------------------------------------------------
# 1. Overlay injector
# ---------------------------------------------------------------------------
def inject_overlay(page, text: str, anchor: str = "top") -> None:
    """Inject a styled <div data-overlay> on the page.

    anchor: "top" or "bottom" — controls vertical placement. Multiple overlays
    can coexist; the recorder is responsible for calling clear_overlays()
    between beats it wants to fully reset.
    """
    position = "top: 24px;" if anchor == "top" else "bottom: 24px;"
    page.evaluate(
        """({text, position}) => {
            const el = document.createElement('div');
            el.dataset.overlay = '1';
            el.textContent = text;
            el.style.cssText = `
                position: fixed;
                ${position}
                left: 50%;
                transform: translateX(-50%);
                background: rgba(15, 23, 42, 0.92);
                color: #f8fafc;
                font-family: ui-sans-serif, system-ui, sans-serif;
                font-size: 22px;
                font-weight: 600;
                padding: 12px 24px;
                border-radius: 8px;
                box-shadow: 0 6px 24px rgba(0,0,0,0.3);
                z-index: 999999;
                white-space: pre;
                letter-spacing: 0.01em;
            `;
            document.body.appendChild(el);
        }""",
        {"text": text, "position": position},
    )


# ---------------------------------------------------------------------------
# 2. Overlay clearer
# ---------------------------------------------------------------------------
def clear_overlays(page) -> None:
    """Remove every injected overlay and every highlight outline."""
    page.evaluate(
        """() => {
            document.querySelectorAll('[data-overlay]').forEach(e => e.remove());
            document.querySelectorAll('[data-highlight]').forEach(e => {
                e.style.outline = '';
                e.style.outlineOffset = '';
                e.style.boxShadow = '';
                delete e.dataset.highlight;
            });
        }"""
    )


# ---------------------------------------------------------------------------
# 3. Concurrent zone burst
# ---------------------------------------------------------------------------
def _post_telemetry(event: dict) -> int:
    body = json.dumps(event).encode()
    req = urllib.request.Request(
        f"{BACKEND}/telemetry",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def fire_zone_burst(count: int, zone_id: str) -> int:
    """Fire `count` concurrent POST /telemetry events, each with zone_entered=zone_id.

    Round-robins vehicle_id across v-00..v-49. Each event has a unique
    microsecond timestamp so they don't dedupe. Returns the number of 2xx
    responses (sanity).
    """
    rng = random.Random(0xC0FFEE)
    events = []
    for i in range(count):
        vid = f"v-{i % 50:02d}"
        ts = datetime.now(timezone.utc).isoformat()
        events.append({
            "vehicle_id": vid,
            "timestamp": ts,
            "lat": 37.41 + rng.random() * 0.001,
            "lon": -122.08 + rng.random() * 0.001,
            "battery_pct": 80.0,
            "speed_mps": 1.0,
            "status": "moving",
            "error_codes": [],
            "zone_entered": zone_id,
        })
    ok = 0
    with ThreadPoolExecutor(max_workers=50) as pool:
        for status in pool.map(_post_telemetry, events):
            if 200 <= status < 300:
                ok += 1
    return ok


# ---------------------------------------------------------------------------
# 4. Concurrent fault burst
# ---------------------------------------------------------------------------
def _post_fault(vehicle_id: str) -> int:
    body = json.dumps({"new_status": "fault"}).encode()
    req = urllib.request.Request(
        f"{BACKEND}/vehicles/{vehicle_id}/status",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def fire_fault_burst(vehicle_id: str, count: int = 10) -> int:
    """Fire `count` concurrent POST /vehicles/{vid}/status {new_status: fault}.

    Returns the number of 2xx responses. With BEGIN IMMEDIATE serialization,
    only one of them creates the maintenance record; the others observe
    status='fault' and short-circuit.
    """
    ok = 0
    with ThreadPoolExecutor(max_workers=count) as pool:
        for status in pool.map(lambda _: _post_fault(vehicle_id), range(count)):
            if 200 <= status < 300:
                ok += 1
    return ok


# ---------------------------------------------------------------------------
# 5. SQL count helper
# ---------------------------------------------------------------------------
def db_count(query: str) -> int:
    """Run a one-column-one-row SELECT against the live SQLite DB.

    The DB is opened in WAL mode by the backend; sqlite3 CLI reads a
    consistent snapshot without blocking writers.
    """
    result = subprocess.run(
        ["sqlite3", DB_PATH, query],
        capture_output=True,
        text=True,
        check=True,
    )
    out = result.stdout.strip()
    if not out:
        return 0
    return int(out.splitlines()[0])


# ---------------------------------------------------------------------------
# 6. Highlight overlay
# ---------------------------------------------------------------------------
def highlight_element(page, selector: str, color: str = "yellow") -> None:
    """Outline the first element matching `selector` with a thick colored ring.

    Idempotent: re-calling with the same selector replaces the previous
    outline. clear_overlays() removes all highlights.
    """
    page.evaluate(
        """({selector, color}) => {
            const el = document.querySelector(selector);
            if (!el) return;
            el.dataset.highlight = '1';
            el.style.outline = `3px solid ${color}`;
            el.style.outlineOffset = '2px';
            el.style.boxShadow = `0 0 0 6px ${color}33`;
        }""",
        {"selector": selector, "color": color},
    )


# ---------------------------------------------------------------------------
# 7. Ambient simulator — background daemon thread
# ---------------------------------------------------------------------------
_ambient_stop = threading.Event()


def _ambient_loop() -> None:
    rng = random.Random(0xA1B2)
    tick = 0
    while not _ambient_stop.is_set():
        events = []
        for i in range(50):
            vid = f"v-{i:02d}"
            events.append({
                "vehicle_id": vid,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "lat": 37.41 + rng.random() * 0.001,
                "lon": -122.08 + rng.random() * 0.001,
                "battery_pct": max(0.0, 95.0 - (tick % 30) * 0.5 + rng.random() * 5),
                "speed_mps": rng.uniform(0.5, 2.0),
                "status": rng.choice(["moving", "idle", "charging"]),
                "error_codes": [],
                "zone_entered": None,
            })
        try:
            body = json.dumps(events).encode()
            req = urllib.request.Request(
                f"{BACKEND}/telemetry",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass  # don't crash the recording if one tick fails
        tick += 1
        # 1 Hz — matches spec
        _ambient_stop.wait(1.0)


def start_ambient_simulator() -> threading.Thread:
    """Start the 50-vehicle 1 Hz ambient simulator as a daemon thread."""
    _ambient_stop.clear()
    t = threading.Thread(target=_ambient_loop, daemon=True, name="ambient-sim")
    t.start()
    return t


def stop_ambient_simulator() -> None:
    _ambient_stop.set()


# ---------------------------------------------------------------------------
# 8. Tiny HTTP helper for read-side overlays
# ---------------------------------------------------------------------------
def http_get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{BACKEND}{path}", timeout=5) as resp:
        return json.loads(resp.read())
```

**Note on `fire_fault_burst`'s target vehicle:** the burst writes to v-33 only. The ambient simulator above writes to all 50 vehicles every second with a random status from {moving, idle, charging} — once we POST the fault transition, subsequent ambient telemetry events will upsert v-33's status away from `fault`, because `/telemetry` blindly upserts `status` (see `app/routes/telemetry.py` step 2). The recorder must therefore read the post-fault `vehicle-status-v-33` immediately after the 10 s dwell, before the simulator re-overwrites it. If the assertion fails because ambient overwrote, the simpler fix is to exclude v-33 from the simulator loop. **Action for recorder:** modify `_ambient_loop` to skip v-33 once `fire_fault_burst` has been called. Easiest implementation: a module-level `EXCLUDED: set[str]` that `fire_fault_burst` adds the target into, and the loop filters out.

---

## Section 5 — Recording configuration

```python
# demo/record.py — entry point
from playwright.sync_api import sync_playwright
from recorder_helpers import (
    inject_overlay, clear_overlays, fire_zone_burst, fire_fault_burst,
    db_count, highlight_element, start_ambient_simulator, stop_ambient_simulator,
    http_get_json,
)

VIEWPORT = {"width": 1440, "height": 900}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport=VIEWPORT,
        record_video_dir="/Users/jorgenino/Documents/telemetry/demo/raw/",
        record_video_size=VIEWPORT,
        device_scale_factor=2,  # crisper text in the recording
    )
    page = context.new_page()
    page.goto("http://127.0.0.1:5173", wait_until="networkidle")
    # ... execute beats per Section 3 ...
    context.close()      # flushes the webm
    browser.close()
```

### ffmpeg post-processing

Playwright writes `.webm` (VP8). Convert to `.mp4` (H.264) for portable playback. Target ≤ 10 MB at 1440×900, 30 fps:

```bash
ffmpeg -y -i /Users/jorgenino/Documents/telemetry/demo/raw/*.webm \
  -c:v libx264 -preset slow -crf 26 -pix_fmt yuv420p \
  -movflags +faststart -an \
  /Users/jorgenino/Documents/telemetry/demo/demo.mp4
```

- `-crf 26` — visually lossless-ish for a screencap with small text. Lower = bigger file; do not go below 22.
- `-an` — strip audio (we have none, but the muxer otherwise embeds a silent track that some players misreport).
- `-pix_fmt yuv420p` — required for Safari / QuickTime compatibility.
- `-movflags +faststart` — moves the moov atom to the front so the file plays as it downloads (relevant if uploaded anywhere web-served).
- Expected output size at these settings, 150 s, mostly-static UI: 3–8 MB. If it lands above 12 MB, bump CRF to 28.

---

## Section 6 — Things explicitly NOT in the demo

Mirrors the spirit of ADR §4 ("what I deliberately left out"):

- **Mission IDs on screen.** The dashboard doesn't surface mission rows. Adding a fetch + overlay solely for the demo would be feature creep, and the auto-int IDs don't read well on screen anyway (no "M-1234" format). The fault beat proves mission cancellation indirectly via the maintenance-record count — one record means the atomic path ran exactly once.
- **A live aggregate fleet breakdown chart.** `GET /fleet/state` is shown once as a static text overlay in Beat 5. A real-time bar chart would need a charting library; the ADR explicitly cut chart polish for the same reason.
- **Mobile viewport.** Per qa-report P2-1, 375 px overflows the table. The recording is at 1440×900 — the grader's viewport — and we do not pan to a phone-sized view.
- **Sound / narration.** Silent video by spec. All commentary is on-screen text overlays. Reasoning: deterministic across machines, no audio drift in ffmpeg post, easier to caption.
- **A "before" state reset between takes.** Re-running the script accumulates zone counts and leaves v-33 in `fault`. Documented in Section 1; the recorder is single-take.
- **`/maintenance` endpoint walkthrough.** No such endpoint exists in `app/routes/`. The maintenance-records count is proved via subprocess SQL, which is the honest evidence path.
- **Anomaly drill-down UI.** The AnomalyFeed shows codes + timestamps; we don't open a per-vehicle anomaly history view because the dashboard doesn't have one. The overlay text in Beat 5 names the queryable endpoint instead.
- **Headed browser take.** Headless Chromium is deterministic; a headed run inherits the recorder's OS theme, font hinting, and window-chrome rendering. Not worth the variance.

---

## Appendix — Beat-time sanity check

| Beat | Start | End | Duration |
|---|---|---|---|
| Title | 0:00 | 0:08 | 0:08 |
| Highlight Vehicles | 0:08 | 0:16 | 0:08 |
| Highlight Zones | 0:16 | 0:23 | 0:07 |
| Highlight Anomalies + clock | 0:23 | 0:30 | 0:07 |
| Ambient ingestion | 0:30 | 0:50 | 0:20 |
| Zone burst — pre-read | 0:50 | 0:55 | 0:05 |
| Zone burst — fire | 0:55 | 1:05 | 0:10 |
| Zone burst — post-read | 1:05 | 1:15 | 0:10 |
| Fault — pre-read | 1:15 | 1:20 | 0:05 |
| Fault — fire | 1:20 | 1:30 | 0:10 |
| Fault — post-read + SQL | 1:30 | 1:45 | 0:15 |
| Anomalies + fleet JSON | 1:45 | 2:00 | 0:15 |
| Anomaly dwell | 2:00 | 2:10 | 0:10 |
| End card | 2:10 | 2:30 | 0:20 |
| **Total** | | | **2:30** |

Sum = 150 s = 2:30. Confirmed.
