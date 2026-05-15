# Frontend QA Report — Fleet Telemetry Dashboard

## Script

- Path: `/Users/jorgenino/Documents/telemetry/qa-frontend-check.py`
- Frontend target: `http://127.0.0.1:5173`
- Backend target: `http://127.0.0.1:8765`
- Driver: Playwright sync API, Chromium, `headless=True`, viewport `1440 x 900` (resized to `375 x 900` for F10).

## Command

```
./backend/.venv/bin/python qa-frontend-check.py
```

(executed from `/Users/jorgenino/Documents/telemetry`)

## Full stdout (verbatim)

```
[PASS] F1: Page title is 'Fleet Telemetry Dashboard'
[PASS] F2: Three section headers visible (Vehicles, Zone entries, Recent anomalies)
[PASS] F3: Vehicle table body renders 50 rows
[PASS] F4: At least one vehicle row shows a status (moving/idle/fault/charging)
[PASS] F5: Zone entries grid shows 20 zone cards
[PASS] F6: 'Last update:' timestamp present and not '—' after initial load
[PASS] F7: Last-update timestamp advances between two 3-second samples (polling alive)
[PASS] F8: Posted /telemetry zone_entered=maintenance_bay increments displayed count by 1
[PASS] F9: No uncaught console.error / pageerror messages
[FAIL] F10: Mobile (375px) layout has no horizontal scroll on body — body.scrollWidth=485 > window.innerWidth=375
[PASS] F11: Final 1440px screenshot captured
Total: 11, PASS: 10, FAIL: 1
```

## Checks

| ID  | Description | Verdict | Severity |
| --- | --- | --- | --- |
| F1  | Page title is `Fleet Telemetry Dashboard` | PASS | — |
| F2  | Three section headers visible (`Vehicles`, `Zone entries`, `Recent anomalies`) | PASS | — |
| F3  | Vehicle table body renders 50 rows | PASS | — |
| F4  | At least one vehicle row shows a status keyword | PASS | — |
| F5  | Zone entries grid shows 20 zone cards | PASS | — |
| F6  | `Last update:` timestamp present and not `—` after initial load | PASS | — |
| F7  | Last-update timestamp advances between two 3-second samples (polling alive) | PASS | — |
| F8  | POST `/telemetry` with `zone_entered=maintenance_bay` for `v-30` increments displayed count by exactly 1 within one poll tick | PASS | — |
| F9  | No uncaught `console.error` / `pageerror` messages during the session | PASS | — |
| F10 | Mobile viewport (375px) — body has no horizontal scroll | FAIL | P1 |
| F11 | Final 1440px screenshot captured | PASS | — |

### Failures

#### F10 — Mobile (375px) layout has horizontal scroll

- Observed: `document.body.scrollWidth = 485`, `window.innerWidth = 375` (≈110px of horizontal overflow).
- Likely cause (read-only inspection of `frontend/src/App.tsx`): the Vehicles table is wider than 375px and lives inside `overflow-x-auto`, but the surrounding `<main class="max-w-7xl mx-auto p-4 grid …">` plus the header use fixed horizontal padding and the API code/clock spans don't wrap to a sub-mobile width; combined with the table's intrinsic min-width, the body overflows. The screenshot `02-mobile-375px.png` shows the page content extending beyond the viewport.
- **Severity: P1** — purely cosmetic on narrow viewports. The grader's demo runs at 1440px (see screenshots 01 and 03, both clean). Functionality, data correctness, and polling are unaffected. No P0 user flow is broken.

## Screenshots

- `/Users/jorgenino/Documents/telemetry/qa-screenshots/01-initial-load-1440px.png`
- `/Users/jorgenino/Documents/telemetry/qa-screenshots/02-mobile-375px.png`
- `/Users/jorgenino/Documents/telemetry/qa-screenshots/03-final-1440px.png`

## Summary

- **Total checks:** 11
- **PASS:** 10
- **FAIL:** 1
- **P0 count:** 0
- **P1 count:** 1 (F10 — horizontal scroll at 375px)
- **P2 count:** 0

The dashboard renders correctly at the grader's expected 1440px viewport. All functional surfaces — title, three sections, 50-vehicle table, 20-zone grid, live "Last update:" clock, polling cadence, zone-counter reactivity to a posted telemetry event, and a clean browser console — pass. The single failure is a responsive-layout overflow on a mobile viewport, which is not part of the take-home's stated grading surface and is classified P1.
