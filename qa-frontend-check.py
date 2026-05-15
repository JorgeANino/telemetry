"""Frontend QA harness for the Fleet Telemetry Dashboard.

Drives Chromium via Playwright (sync API), exercises the live dashboard at
http://127.0.0.1:5173, captures screenshots, and asserts the eleven F-series
checks defined in the QA brief. Each check prints a verdict line.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path("/Users/jorgenino/Documents/telemetry")
SHOTS = ROOT / "qa-screenshots"
SHOTS.mkdir(exist_ok=True)

FRONTEND = "http://127.0.0.1:5173"
BACKEND = "http://127.0.0.1:8765"

results: list[tuple[str, bool, str]] = []  # (id, passed, message)


def record(check_id: str, passed: bool, description: str, reason: str = "") -> None:
    """Print a verdict line and record it for the summary."""
    if passed:
        print(f"[PASS] {check_id}: {description}")
    else:
        print(f"[FAIL] {check_id}: {description} — {reason}")
    results.append((check_id, passed, description if passed else f"{description} — {reason}"))


def extract_last_update(page) -> str:
    """Read the 'Last update:' value from the header.

    The header renders 'Last update:' label and a sibling span with the clock.
    Locate by text and then grab the adjacent monospace span.
    """
    # The label span contains 'Last update:' and a nested span with the clock.
    el = page.locator("span", has_text="Last update:").first
    text = el.inner_text().strip()
    # Strip the label prefix
    m = re.search(r"Last update:\s*(.+)", text)
    return m.group(1).strip() if m else text


def get_maintenance_bay_count(page) -> int | None:
    """Return the displayed entry_count for the 'maintenance_bay' zone card."""
    # Each zone card has a div with the zone id (font-mono) and a sibling div
    # with the count. Locate the card via its text id.
    card = page.locator("div", has_text=re.compile(r"^maintenance_bay$")).first
    # Use a more robust approach: find via the id text within a card div.
    cards = page.locator("div.border.rounded")
    n = cards.count()
    for i in range(n):
        c = cards.nth(i)
        try:
            txt = c.inner_text()
        except Exception:
            continue
        if "maintenance_bay" in txt:
            # Count is on the second line of the card
            lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
            for ln in lines:
                if ln.isdigit():
                    return int(ln)
    return None


def main() -> int:
    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Attach console + pageerror listeners BEFORE navigation.
        def on_console(msg):
            if msg.type == "error":
                console_errors.append(f"[console.error] {msg.text}")

        page.on("console", on_console)
        page.on("pageerror", lambda err: page_errors.append(f"[pageerror] {err}"))

        # 2. Navigate
        page.goto(FRONTEND, wait_until="networkidle")
        # 3. Wait the polling tick
        time.sleep(3)

        # 4. Initial screenshot
        page.screenshot(path=str(SHOTS / "01-initial-load-1440px.png"), full_page=True)

        # F1: page title
        title = page.title()
        record(
            "F1",
            title == "Fleet Telemetry Dashboard",
            "Page title is 'Fleet Telemetry Dashboard'",
            f"got {title!r}",
        )

        # F2: three section headers visible
        wanted = ["Vehicles", "Zone entries", "Recent anomalies"]
        missing = []
        for name in wanted:
            loc = page.get_by_role("heading", name=name)
            try:
                if loc.count() == 0 or not loc.first.is_visible():
                    missing.append(name)
            except Exception:
                missing.append(name)
        record(
            "F2",
            not missing,
            "Three section headers visible (Vehicles, Zone entries, Recent anomalies)",
            f"missing: {missing}",
        )

        # F3: vehicle rows == 50
        rows = page.locator("table tbody tr")
        n_rows = rows.count()
        record(
            "F3",
            n_rows == 50,
            "Vehicle table body renders 50 rows",
            f"got {n_rows}",
        )

        # F4: at least one row shows a status keyword
        status_words = ["moving", "idle", "fault", "charging"]
        body_text = page.locator("table tbody").inner_text()
        found_any = any(w in body_text for w in status_words)
        record(
            "F4",
            found_any,
            "At least one vehicle row shows a status (moving/idle/fault/charging)",
            "no status keyword found in table body",
        )

        # F5: zone cards == 20
        zone_cards = page.locator("div.grid.grid-cols-2 > div.border")
        n_zones = zone_cards.count()
        record(
            "F5",
            n_zones == 20,
            "Zone entries grid shows 20 zone cards",
            f"got {n_zones}",
        )

        # F6: 'Last update:' is present and not '—'
        try:
            lu = extract_last_update(page)
        except Exception as e:
            lu = f"<error: {e}>"
        record(
            "F6",
            bool(lu) and lu != "—" and "<error" not in lu,
            "'Last update:' timestamp present and not '—' after initial load",
            f"got {lu!r}",
        )

        # F7: polling alive — two captures 3s apart should differ
        time.sleep(3)
        t1 = extract_last_update(page)
        time.sleep(3)
        t2 = extract_last_update(page)
        record(
            "F7",
            t1 != t2,
            "Last-update timestamp advances between two 3-second samples (polling alive)",
            f"t1={t1!r} t2={t2!r}",
        )

        # F8: injected telemetry — maintenance_bay count must go up by 1.
        before = get_maintenance_bay_count(page)
        # Fire one telemetry event for v-30 entering maintenance_bay.
        ts = datetime.now(timezone.utc).isoformat()
        try:
            r = httpx.post(
                f"{BACKEND}/telemetry",
                json={
                    "vehicle_id": "v-30",
                    "timestamp": ts,
                    "lat": 37.4,
                    "lon": -122.1,
                    "battery_pct": 67.0,
                    "speed_mps": 1.0,
                    "status": "moving",
                    "error_codes": [],
                    "zone_entered": "maintenance_bay",
                },
                timeout=5.0,
            )
            post_ok = r.status_code in (200, 202)
            post_status = r.status_code
        except Exception as e:
            post_ok = False
            post_status = f"exception: {e}"

        # Wait long enough for the 2s frontend poll to fire AND complete.
        time.sleep(4)
        after = get_maintenance_bay_count(page)
        if not post_ok:
            record(
                "F8",
                False,
                "Posted /telemetry zone_entered=maintenance_bay increments displayed count by 1",
                f"POST failed: {post_status}",
            )
        elif before is None or after is None:
            record(
                "F8",
                False,
                "Posted /telemetry zone_entered=maintenance_bay increments displayed count by 1",
                f"could not read counts (before={before}, after={after})",
            )
        else:
            record(
                "F8",
                after == before + 1,
                "Posted /telemetry zone_entered=maintenance_bay increments displayed count by 1",
                f"before={before} after={after} (expected before+1)",
            )

        # F9: no uncaught console / page errors
        all_errors = console_errors + page_errors
        record(
            "F9",
            len(all_errors) == 0,
            "No uncaught console.error / pageerror messages",
            f"{len(all_errors)} error(s): {all_errors}",
        )
        if all_errors:
            print("  --- captured browser errors ---")
            for e in all_errors:
                print(f"  {e}")
            print("  --- end errors ---")

        # F10: 375px mobile — no horizontal scroll on body
        page.set_viewport_size({"width": 375, "height": 900})
        time.sleep(1)  # allow layout to settle
        page.screenshot(path=str(SHOTS / "02-mobile-375px.png"), full_page=True)
        has_hscroll = page.evaluate(
            "() => document.body.scrollWidth > window.innerWidth"
        )
        details = ""
        if has_hscroll:
            sw = page.evaluate("() => document.body.scrollWidth")
            iw = page.evaluate("() => window.innerWidth")
            details = f"body.scrollWidth={sw} > window.innerWidth={iw}"
        record(
            "F10",
            not has_hscroll,
            "Mobile (375px) layout has no horizontal scroll on body",
            details or "horizontal overflow present",
        )

        # F11: back to 1440 — final screenshot
        page.set_viewport_size({"width": 1440, "height": 900})
        time.sleep(1)
        page.screenshot(path=str(SHOTS / "03-final-1440px.png"), full_page=True)
        record(
            "F11",
            (SHOTS / "03-final-1440px.png").exists(),
            "Final 1440px screenshot captured",
            "screenshot file missing",
        )

        browser.close()

    total = len(results)
    n_pass = sum(1 for _, ok, _ in results if ok)
    n_fail = total - n_pass
    print(f"Total: {total}, PASS: {n_pass}, FAIL: {n_fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
