"""Fleet Telemetry demo recorder.

Spec: demo/demo-script.md. This script orchestrates Playwright to record a
~150 s silent screencast of the fleet dashboard, with overlay annotations and
backend bursts to demonstrate concurrent ingest + atomic fault transitions.

Run:
    /Users/jorgenino/Documents/telemetry/backend/.venv/bin/python \
        /Users/jorgenino/Documents/telemetry/demo/record_demo.py
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import imageio_ffmpeg
from playwright.sync_api import Page, sync_playwright

# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

BACKEND = "http://127.0.0.1:8765"
FRONTEND = "http://127.0.0.1:5173/"
DB_PATH = "/Users/jorgenino/Documents/telemetry/backend/telemetry.db"
DEMO_DIR = Path("/Users/jorgenino/Documents/telemetry/demo")
RAW_DIR = DEMO_DIR / "raw"
TARGET_VEHICLE = "v-33"
TARGET_ZONE = "charging_bay_1"
VIEWPORT = {"width": 1440, "height": 900}

# --------------------------------------------------------------------------- #
# Ambient simulator state                                                     #
# --------------------------------------------------------------------------- #

_ambient_stop = threading.Event()
_excluded_lock = threading.Lock()
_excluded: set[str] = set()


def excluded_add(vid: str) -> None:
    with _excluded_lock:
        _excluded.add(vid)


def excluded_snapshot() -> set[str]:
    with _excluded_lock:
        return set(_excluded)


# --------------------------------------------------------------------------- #
# Pre-flight checks                                                           #
# --------------------------------------------------------------------------- #

def preflight() -> None:
    try:
        r = httpx.get(f"{BACKEND}/healthz", timeout=5.0)
        r.raise_for_status()
        body = r.json()
        assert body.get("ok") is True, body
    except Exception as e:
        sys.exit(f"FATAL: backend /healthz check failed: {e}")
    try:
        r = httpx.get(FRONTEND, timeout=5.0)
        assert r.status_code == 200, r.status_code
    except Exception as e:
        sys.exit(f"FATAL: frontend at {FRONTEND} not reachable: {e}")
    print("[preflight] backend + frontend OK")


def reset_target_vehicle() -> None:
    """Reset v-33 to `moving` so the fault beat starts from a known state."""
    try:
        r = httpx.post(
            f"{BACKEND}/vehicles/{TARGET_VEHICLE}/status",
            json={"new_status": "moving"},
            timeout=5.0,
        )
        if not (200 <= r.status_code < 300):
            print(f"[preflight] WARN reset {TARGET_VEHICLE}: HTTP {r.status_code}")
        else:
            print(f"[preflight] reset {TARGET_VEHICLE} -> moving")
    except Exception as e:
        print(f"[preflight] WARN reset {TARGET_VEHICLE}: {e}")


# --------------------------------------------------------------------------- #
# Overlay / highlight helpers                                                 #
# --------------------------------------------------------------------------- #

OVERLAY_STYLE = """
.demo-overlay {
    position: fixed;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(15, 23, 42, 0.92);
    color: #f8fafc;
    padding: 14px 22px;
    border-radius: 10px;
    font: 600 18px/1.4 -apple-system, system-ui, sans-serif;
    box-shadow: 0 12px 32px rgba(0,0,0,0.35);
    z-index: 99999;
    max-width: 80vw;
    text-align: center;
    white-space: pre-line;
}
.demo-overlay.top { top: 24px; }
.demo-overlay.bottom { bottom: 24px; }
.demo-card {
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 42, 0.96);
    color: #f8fafc;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    z-index: 1000000;
    text-align: center;
    font-family: -apple-system, system-ui, sans-serif;
    padding: 40px;
}
.demo-card h1 { font-size: 56px; font-weight: 700; margin: 0 0 16px; letter-spacing: -0.02em; }
.demo-card h2 { font-size: 24px; font-weight: 500; margin: 0; color: #94a3b8; }
.demo-card .lines { font-size: 22px; font-weight: 500; line-height: 1.7; max-width: 80%; }
.demo-card .lines div { margin: 6px 0; }
"""


def install_style(page: Page) -> None:
    page.add_style_tag(content=OVERLAY_STYLE)


def inject_overlay(page: Page, text: str, anchor: str = "top") -> None:
    """Inject a styled overlay div at top or bottom of the viewport."""
    page.evaluate(
        """({text, anchor}) => {
            const el = document.createElement('div');
            el.className = 'demo-overlay ' + anchor;
            el.dataset.overlay = '1';
            el.textContent = text;
            document.body.appendChild(el);
        }""",
        {"text": text, "anchor": anchor},
    )


def clear_overlays(page: Page) -> None:
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


def show_card(page: Page, title: str, subtitle: Optional[str] = None,
              lines: Optional[list[str]] = None) -> None:
    """Render a full-screen card overlay (title screen / end screen)."""
    page.evaluate(
        """({title, subtitle, lines}) => {
            document.querySelectorAll('[data-card]').forEach(e => e.remove());
            const card = document.createElement('div');
            card.dataset.card = '1';
            card.className = 'demo-card';
            if (title) {
                const h1 = document.createElement('h1');
                h1.textContent = title;
                card.appendChild(h1);
            }
            if (subtitle) {
                const h2 = document.createElement('h2');
                h2.textContent = subtitle;
                card.appendChild(h2);
            }
            if (lines && lines.length) {
                const wrap = document.createElement('div');
                wrap.className = 'lines';
                lines.forEach(t => {
                    const d = document.createElement('div');
                    d.textContent = t;
                    wrap.appendChild(d);
                });
                card.appendChild(wrap);
            }
            document.body.appendChild(card);
        }""",
        {"title": title, "subtitle": subtitle, "lines": lines or []},
    )


def hide_card(page: Page) -> None:
    page.evaluate("() => document.querySelectorAll('[data-card]').forEach(e => e.remove())")


def highlight_element(page: Page, selector: str, color: str = "#fbbf24") -> None:
    """Outline the first element matching `selector` with an amber ring.

    Uses Playwright's locator engine (supports :has, :text, etc.) and applies
    inline styles via element_handle().evaluate so we can highlight elements
    that document.querySelector can't address.
    """
    try:
        handle = page.locator(selector).first.element_handle(timeout=2000)
    except Exception:
        return
    if handle is None:
        return
    handle.evaluate(
        """(el, color) => {
            el.dataset.highlight = '1';
            el.style.outline = `3px solid ${color}`;
            el.style.outlineOffset = '4px';
            el.style.boxShadow = `0 0 0 8px ${color}40`;
        }""",
        color,
    )


def highlight_by_heading(page: Page, heading_text: str, color: str = "#fbbf24") -> None:
    """Highlight the <section> whose <h2> contains the given text."""
    sel = f'section:has(h2:has-text("{heading_text}"))'
    highlight_element(page, sel, color)


def show_json_overlay(page: Page, obj: dict, anchor: str = "bottom") -> None:
    """Render a JSON snippet overlay (multiline, monospace)."""
    text = json.dumps(obj, indent=2)
    page.evaluate(
        """({text, anchor}) => {
            const el = document.createElement('div');
            el.className = 'demo-overlay ' + anchor;
            el.dataset.overlay = '1';
            el.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, monospace';
            el.style.fontSize = '16px';
            el.style.textAlign = 'left';
            el.textContent = text;
            document.body.appendChild(el);
        }""",
        {"text": text, "anchor": anchor},
    )


# --------------------------------------------------------------------------- #
# Backend burst helpers                                                       #
# --------------------------------------------------------------------------- #

def _post_telemetry_one(event: dict) -> int:
    with httpx.Client(timeout=10.0) as client:
        r = client.post(f"{BACKEND}/telemetry", json=event)
        return r.status_code


def fire_zone_burst(count: int, zone_id: str) -> int:
    """Fire `count` concurrent POST /telemetry events with zone_entered=zone_id."""
    rng = random.Random(0xC0FFEE)
    events = []
    for i in range(count):
        vid = f"v-{i % 50:02d}"
        events.append({
            "vehicle_id": vid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
        futures = [pool.submit(_post_telemetry_one, ev) for ev in events]
        done, _ = wait(futures)
        for f in done:
            try:
                if 200 <= f.result() < 300:
                    ok += 1
            except Exception:
                pass
    return ok


def _post_fault_one(vehicle_id: str) -> int:
    with httpx.Client(timeout=10.0) as client:
        r = client.post(
            f"{BACKEND}/vehicles/{vehicle_id}/status",
            json={"new_status": "fault"},
        )
        return r.status_code


def fire_fault_burst(vehicle_id: str, count: int = 10) -> int:
    """Fire `count` concurrent fault transitions; exclude vehicle from ambient sim."""
    ok = 0
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(_post_fault_one, vehicle_id) for _ in range(count)]
        done, _ = wait(futures)
        for f in done:
            try:
                if 200 <= f.result() < 300:
                    ok += 1
            except Exception:
                pass
    # Critical: stop ambient sim from clobbering v-33's fault status
    excluded_add(vehicle_id)
    return ok


# --------------------------------------------------------------------------- #
# DB count helper                                                             #
# --------------------------------------------------------------------------- #

def db_count(query: str) -> int:
    result = subprocess.run(
        ["sqlite3", DB_PATH, query],
        capture_output=True, text=True, check=True,
    )
    out = result.stdout.strip()
    if not out:
        return 0
    return int(out.splitlines()[0])


# --------------------------------------------------------------------------- #
# Ambient simulator                                                           #
# --------------------------------------------------------------------------- #

def _ambient_loop() -> None:
    rng = random.Random(0xA1B2)
    tick = 0
    while not _ambient_stop.is_set():
        excl = excluded_snapshot()
        events = []
        for i in range(50):
            vid = f"v-{i:02d}"
            if vid in excl:
                continue
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
            with httpx.Client(timeout=5.0) as client:
                client.post(f"{BACKEND}/telemetry", json=events)
        except Exception:
            pass
        tick += 1
        _ambient_stop.wait(1.0)


def start_ambient_simulator() -> threading.Thread:
    _ambient_stop.clear()
    with _excluded_lock:
        _excluded.clear()
    t = threading.Thread(target=_ambient_loop, daemon=True, name="ambient-sim")
    t.start()
    return t


def stop_ambient_simulator() -> None:
    _ambient_stop.set()


# --------------------------------------------------------------------------- #
# HTTP read helper                                                            #
# --------------------------------------------------------------------------- #

def http_get_json(path: str) -> dict:
    with httpx.Client(timeout=5.0) as client:
        r = client.get(f"{BACKEND}{path}")
        r.raise_for_status()
        return r.json()


# --------------------------------------------------------------------------- #
# Beat-by-beat recording                                                      #
# --------------------------------------------------------------------------- #

def read_zone_count(page: Page, zone: str) -> int:
    txt = page.locator(f'[data-testid="zone-count-{zone}"]').text_content() or "0"
    return int(txt.strip())


def read_vehicle_status(page: Page, vid: str) -> str:
    txt = page.locator(f'[data-testid="vehicle-status-{vid}"]').text_content() or ""
    return txt.strip()


def run_beats(page: Page) -> int:
    """Execute the beat list. Returns total beat count."""
    beats = 0
    install_style(page)

    # Wait for initial poll so the dashboard isn't blank
    page.wait_for_selector('[data-testid="last-updated"]', timeout=10000)
    page.wait_for_timeout(2500)

    # ----- Beat 1: Title card (0:00-0:08, 8s) ---------------------------------
    show_card(page, "Fleet Telemetry",
              subtitle="50 vehicles | 1 Hz | concurrent-safe ingest")
    page.wait_for_timeout(8000)
    hide_card(page)
    beats += 1

    # ----- Beat 2: Highlight Vehicles panel (0:08-0:16, 8s) -------------------
    # The Vehicles section is the first <section> with data-testid vehicle-row-*
    highlight_element(page, 'section:has([data-testid^="vehicle-row-"])')
    inject_overlay(page, "Live vehicle list - status, battery, latest anomaly", "top")
    page.wait_for_timeout(8000)
    clear_overlays(page)
    beats += 1

    # ----- Beat 3: Highlight Zone entries (0:16-0:23, 7s) ---------------------
    highlight_element(page, 'section:has([data-testid^="zone-card-"])')
    inject_overlay(page, "Zone entry counters - 20 zones, incremented on zone_entered", "top")
    page.wait_for_timeout(7000)
    clear_overlays(page)
    beats += 1

    # ----- Beat 4: Highlight Anomalies + clock (0:23-0:30, 7s) ---------------
    # AnomalyFeed is the section with heading "Recent anomalies"
    highlight_by_heading(page, "Recent anomalies")
    highlight_element(page, '[data-testid="last-updated"]')
    inject_overlay(page, "Anomaly feed + 2 s poll clock", "top")
    page.wait_for_timeout(7000)
    clear_overlays(page)
    beats += 1

    # ----- Beat 5: Ambient ingestion (0:30-0:50, 20s) ------------------------
    # Ambient simulator was started before run_beats; here we just dwell.
    inject_overlay(page, "Live ingestion: 50 vehicles @ 1 Hz", "top")
    page.wait_for_timeout(20000)
    clear_overlays(page)
    beats += 1

    # ----- Beat 6: Zone burst pre-read (0:50-0:55, 5s) -----------------------
    highlight_element(page, f'[data-testid="zone-card-{TARGET_ZONE}"]')
    # Wait briefly for the zone card to be visible (might need polling tick)
    try:
        page.locator(f'[data-testid="zone-count-{TARGET_ZONE}"]').wait_for(
            state="visible", timeout=5000
        )
    except Exception:
        pass
    before = read_zone_count(page, TARGET_ZONE)
    inject_overlay(page, f"{TARGET_ZONE} count: {before}", "bottom")
    page.wait_for_timeout(5000)
    clear_overlays(page)
    beats += 1

    # ----- Beat 7: Zone burst fire (0:55-1:05, 10s) --------------------------
    highlight_element(page, f'[data-testid="zone-card-{TARGET_ZONE}"]')
    inject_overlay(
        page,
        f"Firing 200 concurrent POSTs -> /telemetry with zone_entered={TARGET_ZONE}",
        "top",
    )
    burst_ok = fire_zone_burst(count=200, zone_id=TARGET_ZONE)
    print(f"[beat7] zone burst: {burst_ok}/200 OK")
    page.wait_for_timeout(10000)
    clear_overlays(page)
    beats += 1

    # ----- Beat 8: Zone burst post-read (1:05-1:15, 10s) ---------------------
    highlight_element(page, f'[data-testid="zone-card-{TARGET_ZONE}"]')
    after = read_zone_count(page, TARGET_ZONE)
    delta = after - before
    mark = "OK" if delta == 200 else "MISMATCH"
    inject_overlay(
        page,
        f"Expected delta: +200    Actual delta: +{delta} {mark}",
        "bottom",
    )
    print(f"[beat8] zone {TARGET_ZONE}: before={before} after={after} delta={delta}")
    page.wait_for_timeout(10000)
    clear_overlays(page)
    beats += 1

    # ----- Beat 9: Fault pre-read (1:15-1:20, 5s) ----------------------------
    page.locator(f'[data-testid="vehicle-row-{TARGET_VEHICLE}"]').scroll_into_view_if_needed()
    highlight_element(page, f'[data-testid="vehicle-row-{TARGET_VEHICLE}"]')
    pre_status = read_vehicle_status(page, TARGET_VEHICLE)
    pre_maint = db_count(
        f"SELECT COUNT(*) FROM maintenance_records WHERE vehicle_id='{TARGET_VEHICLE}'"
    )
    inject_overlay(
        page,
        f"{TARGET_VEHICLE} status: {pre_status}    maintenance_records: {pre_maint}",
        "bottom",
    )
    print(f"[beat9] {TARGET_VEHICLE}: pre_status={pre_status} pre_maint={pre_maint}")
    page.wait_for_timeout(5000)
    clear_overlays(page)
    beats += 1

    # ----- Beat 10: Fault burst fire (1:20-1:30, 10s) ------------------------
    highlight_element(page, f'[data-testid="vehicle-row-{TARGET_VEHICLE}"]')
    inject_overlay(
        page,
        f"10 concurrent POST -> /vehicles/{TARGET_VEHICLE}/status {{new_status: fault}}",
        "top",
    )
    fault_ok = fire_fault_burst(TARGET_VEHICLE, count=10)
    print(f"[beat10] fault burst: {fault_ok}/10 OK, v-33 now excluded from ambient")
    page.wait_for_timeout(10000)
    clear_overlays(page)
    beats += 1

    # ----- Beat 11: Fault post-read (1:30-1:45, 15s) -------------------------
    highlight_element(page, f'[data-testid="vehicle-row-{TARGET_VEHICLE}"]')
    post_status = read_vehicle_status(page, TARGET_VEHICLE)
    post_maint = db_count(
        f"SELECT COUNT(*) FROM maintenance_records WHERE vehicle_id='{TARGET_VEHICLE}'"
    )
    delta_maint = post_maint - pre_maint
    mark_status = "OK" if post_status == "fault" else "MISMATCH"
    mark_maint = "OK" if delta_maint == 1 else "MISMATCH"
    inject_overlay(
        page,
        f"{TARGET_VEHICLE} status: {post_status} {mark_status}    "
        f"maintenance_records: {post_maint} {mark_maint}",
        "bottom",
    )
    print(f"[beat11] {TARGET_VEHICLE}: post_status={post_status} post_maint={post_maint}")
    page.wait_for_timeout(15000)
    clear_overlays(page)
    beats += 1

    # ----- Beat 12: Anomalies + fleet JSON (1:45-2:00, 15s) ------------------
    page.evaluate("() => window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})")
    page.wait_for_timeout(500)
    highlight_by_heading(page, "Recent anomalies")
    inject_overlay(
        page,
        "Anomaly feed: queryable via GET /anomalies?vehicle_id&from&to",
        "top",
    )
    try:
        fleet = http_get_json("/fleet/state")
        # Distill to status counts if possible; otherwise show whole payload.
        if isinstance(fleet, dict) and "status_counts" in fleet:
            show_json_overlay(page, fleet["status_counts"], anchor="bottom")
        elif isinstance(fleet, dict) and all(
            k in fleet for k in ("idle", "moving", "charging", "fault")
        ):
            show_json_overlay(page, {k: fleet[k] for k in
                                     ("idle", "moving", "charging", "fault")}, anchor="bottom")
        else:
            # Show top-level summary
            summary = {k: v for k, v in fleet.items() if not isinstance(v, (list, dict))}
            show_json_overlay(page, summary or fleet, anchor="bottom")
    except Exception as e:
        print(f"[beat12] fleet/state fetch failed: {e}")
        inject_overlay(page, "GET /fleet/state", "bottom")
    page.wait_for_timeout(15000)
    clear_overlays(page)
    beats += 1

    # ----- Beat 13: Anomaly dwell (2:00-2:10, 10s) ---------------------------
    # Scroll the anomaly feed into view, no overlay
    try:
        page.locator('section:has(h2:has-text("Recent anomalies"))').first.scroll_into_view_if_needed()
    except Exception:
        pass
    page.wait_for_timeout(10000)
    beats += 1

    # ----- Beat 14: End card (2:10-2:30, 20s) --------------------------------
    show_card(
        page,
        "Fleet Telemetry",
        subtitle=None,
        lines=[
            "Backend - FastAPI + SQLite WAL | BEGIN IMMEDIATE on fault",
            "Frontend - React + TS | 2 s polling",
            "ADR | AI log | README in repo",
        ],
    )
    page.wait_for_timeout(20000)
    hide_card(page)
    beats += 1

    return beats


# --------------------------------------------------------------------------- #
# ffmpeg post-processing                                                      #
# --------------------------------------------------------------------------- #

def post_process(raw_webm: Path) -> tuple[Path, Path]:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    mp4 = DEMO_DIR / "demo.mp4"
    gif = DEMO_DIR / "demo-preview.gif"

    print(f"[ffmpeg] transcoding {raw_webm.name} -> demo.mp4")
    r = subprocess.run(
        [
            ffmpeg, "-y", "-i", str(raw_webm),
            "-c:v", "libx264", "-preset", "slow", "-crf", "22",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-an",
            str(mp4),
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(r.stderr[-2000:])
        raise RuntimeError("ffmpeg mp4 transcode failed")

    print(f"[ffmpeg] generating preview gif")
    r = subprocess.run(
        [
            ffmpeg, "-y", "-i", str(mp4), "-t", "20",
            "-vf",
            "fps=12,scale=800:-1:flags=lanczos,split[s0][s1];"
            "[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5",
            str(gif),
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(r.stderr[-2000:])
        raise RuntimeError("ffmpeg gif transcode failed")

    # If too big, re-transcode with lower quality
    if mp4.stat().st_size > 25 * 1024 * 1024:
        print("[ffmpeg] mp4 > 25MB, re-transcoding crf=28")
        subprocess.run(
            [
                ffmpeg, "-y", "-i", str(raw_webm),
                "-c:v", "libx264", "-preset", "slow", "-crf", "28",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
                str(mp4),
            ],
            check=True, capture_output=True, text=True,
        )

    if gif.stat().st_size > 25 * 1024 * 1024:
        print("[ffmpeg] gif > 25MB, reducing colors")
        subprocess.run(
            [
                ffmpeg, "-y", "-i", str(mp4), "-t", "15",
                "-vf",
                "fps=10,scale=720:-1:flags=lanczos,split[s0][s1];"
                "[s0]palettegen=max_colors=64[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5",
                str(gif),
            ],
            check=True, capture_output=True, text=True,
        )

    return mp4, gif


def scrub(mp4: Path) -> list[Path]:
    """Extract sanity-check screenshots at key beats."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    paths = []
    for t in ["00:00:30", "00:01:00", "00:01:30", "00:02:00"]:
        label = t.replace(":", "")
        out = DEMO_DIR / f"scrub-{label}.png"
        subprocess.run(
            [ffmpeg, "-y", "-ss", t, "-i", str(mp4), "-vframes", "1", str(out)],
            check=True, capture_output=True, text=True,
        )
        paths.append(out)
    return paths


def get_duration(mp4: Path) -> float:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    # ffprobe is in same dir typically; fall back to ffmpeg -i parsing
    r = subprocess.run(
        [ffmpeg, "-i", str(mp4)], capture_output=True, text=True,
    )
    # Output goes to stderr
    out = r.stderr
    import re
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mn * 60 + s
    return -1.0


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #

def main() -> int:
    preflight()
    reset_target_vehicle()

    # Clear stale webms so we can identify the new one
    for p in RAW_DIR.glob("*.webm"):
        try:
            p.unlink()
            print(f"[cleanup] removed stale {p.name}")
        except Exception:
            pass

    print("[ambient] starting simulator")
    ambient = start_ambient_simulator()

    beats_run = 0
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport=VIEWPORT,
                record_video_dir=str(RAW_DIR),
                record_video_size=VIEWPORT,
            )
            page = context.new_page()
            print(f"[playwright] navigating to {FRONTEND}")
            page.goto(FRONTEND, wait_until="networkidle", timeout=20000)
            try:
                beats_run = run_beats(page)
            finally:
                context.close()  # flush webm
                browser.close()
    finally:
        stop_ambient_simulator()
        ambient.join(timeout=3.0)

    # Find the produced webm
    webms = sorted(RAW_DIR.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not webms:
        sys.exit("FATAL: no webm produced")
    raw = webms[0]
    size_mb = raw.stat().st_size / (1024 * 1024)
    print(f"[recorder] beats={beats_run} raw={raw.name} size={size_mb:.2f} MB")
    if size_mb < 1.0:
        sys.exit(f"FATAL: raw webm < 1 MB ({size_mb:.2f}), recording likely broken")

    mp4, gif = post_process(raw)
    print(f"[output] mp4: {mp4} ({mp4.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"[output] gif: {gif} ({gif.stat().st_size / 1024 / 1024:.2f} MB)")
    dur = get_duration(mp4)
    print(f"[output] duration: {dur:.2f} s")

    scrubs = scrub(mp4)
    for s in scrubs:
        sz = s.stat().st_size
        print(f"[scrub] {s.name} ({sz} bytes)")

    print(f"\n=== SUMMARY ===")
    print(f"Beats:       {beats_run}")
    print(f"mp4:         {mp4} ({mp4.stat().st_size / 1024 / 1024:.2f} MB, {dur:.1f}s)")
    print(f"gif:         {gif} ({gif.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"Scrubs:      {[str(s) for s in scrubs]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
