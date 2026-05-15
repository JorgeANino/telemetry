# AI Interaction Log — Fleet Telemetry Take-Home

**Project:** Fleet telemetry monitoring service (50 vehicles, 1 Hz, ~20 zones)
**Lead:** jorge@devbox.com.mx
**AI tools used:** Claude Code (Opus 4.7) as orchestrator + multiple subagent delegations
**Started:** 2026-05-15

## Phase budgets (5–6 hour total)

| Phase | Goal | Budget | Spent | Status |
|---|---|---|---|---|
| 0 | Spec ingestion + decisions lock-in | 30m | – | in progress |
| 1 | ADR v1 draft | 30m | – | pending |
| 2a | Backend scaffold + data model | 20m | – | pending |
| 2b | Ingestion + anomaly + zone counter | 40m | – | pending |
| 2c | Status update + fault transition | 30m | – | pending |
| 2d | Read endpoints | 20m | – | pending |
| 2e | Load smoke test | 10m | – | pending |
| 3 | Frontend | 90m | – | pending |
| 4 | Verification pass | 30m | – | pending |
| 5 | ADR final + AI log polish + README | 30m | – | pending |

## How this log is maintained

Every meaningful subagent delegation, every redirection, every manual verification is appended here as it happens. No post-hoc reconstruction. Entry schema:

```
## Phase X.Y — <subagent> — <ts>
**Prompt:** <brief sent>
**Output summary:** <2–4 sentences>
**Corrections / redirections:** <or "none">
**Manual verification:** <what I checked myself>
```

---

## Phase 0 — orchestrator (self) — 2026-05-15 09:50

**Decision lock-in (not delegated):** wrote `decisions.md` with one paragraph each for the four top-level choices:

1. **SQLite + WAL** over Postgres — 50 writes/s is two orders of magnitude under SQLite's WAL ceiling; serialized writers turn the zone counter and fault transition into trivially-correct cases; zero ops for graders.
2. **FastAPI** over Django REST — 5 endpoints is too small a surface for DRF ceremony; Pydantic handles the mixed-nullable payload shape cleanly.
3. **Polling at 2 s** over WebSockets — spec asserts no real-time SLA; 1.5 req/s of dashboard load is negligible; WS adds a state machine for no visible win.
4. **Anomaly = `battery_drop > 20` vs prior event, OR `speed > 5 m/s`, OR non-empty `error_codes`, OR `status == "fault"`.** Each rule evaluable against the inbound event + one cached prior event — no windows, no cron, no rolling buffers.

**Manual verification:** none yet — these are policy choices that will be tested by the implementation phases.

## QA Phase A — 4 parallel QA subagents — 2026-05-15 17:30

**Pre-flight (not delegated):** confirmed backend (8765) and frontend (5173) were still serving from the prior session. Installed Playwright + Chromium 1217 + `imageio-ffmpeg` (static ffmpeg binary, no Homebrew dependency) into `backend/.venv`. Total install time ~2 min, run in background while QA agents launched.

**Subagents launched in parallel** (4 background tasks):
1. `functional-qa` — curl every endpoint behavior from `checklist.md`, malformed-input cases.
2. `concurrency-qa` — write `backend/tests/qa_concurrency.py` with 3 live-backend tests (200-burst zone counter, 10-concurrent fault on v-20, fleet-state-under-1000-writes).
3. `frontend-qa` — Playwright script `qa-frontend-check.py` with 11 checks at 1440 px + 1 mobile check, screenshots, console-error sniffer, end-to-end reactivity (POST → UI tick).
4. `docs-qa` — line-numbered review of `ADR.md`, `ai-log.md`, `README.md` against spec rubric.

**Aggregated tally:** 75 checks total, 72 PASS, 2 P1, 0 real P0. One alleged P0 (functional-qa Test 32: `/anomalies` time filter "ignored") was reproduced and rejected — the agent invented param names `?from_ts=…&to_ts=…` instead of the endpoint's actual aliased `?from=…&to=…`. FastAPI silently drops unknown query params and falls back to the default 1h window, which is why every one of the agent's queries returned the same rows.

**Corrections / redirections:**
- **Rejected functional-qa's alleged P0.** Reproduced with correct param names: `?from=2030-…&to=2030-…` → `0 rows` (future window correctly empty); `?from=2019-…&to=2030-…` → `54 rows` (wide window includes all). Filter works. Documented the rejection with evidence in `qa-report.md` rather than silently dropping it — graders should see that a P0 was claimed, investigated, and dismissed.
- **Accepted docs-qa's P1 on Reflections placement.** The block was at line 61 (after Phase 5, with all earlier phases below it) because my log uses reverse-chronological order. Spec says "at the end", which is structurally not where it was. Moved to EOF.
- **Accepted frontend-qa's P1 as P2.** Mobile 375 px viewport overflows because the Vehicles table is wider than 375 px. Demo viewport is 1440 px and spec doesn't require mobile — wrong cost-to-grade ratio to fix. Documented as P2.
- **basedpyright diagnostic on `db.py:27`** is a false positive (`_set_sqlite_pragmas` is registered by SQLAlchemy's `@event.listens_for(Engine, "connect")` decorator; `connection_record` is required by the "connect" event signature). Documented as P2 in `qa-report.md`, not changing code.

**Manual verification:**
- Read all four QA report files top to bottom.
- Reproduced the alleged P0 myself via curl with both the wrong param names (got the agent's behavior) and the right param names (got expected behavior). The 30-second reproduction proved the filter was fine and saved a needless backend "fix" that would have introduced a real bug.
- Cross-checked the concurrency-qa numbers against my own canary test results from Phase 2b/2c: 200-burst still hits 200, fault transition still produces exactly 1 record. The QA tests are independent of the test fixtures (they hit the live backend), so this is a second piece of evidence for the same property.

**Fixes applied in Phase B (both P1):**
- README: added an explicit `?from=…&to=…` curl example under "Try it by hand" so a future tester sees the contract clearly.
- ai-log.md: moved Reflections block from line 61 to the end of file (this current file), no content change.

## Phase 5 — orchestrator (self) — 2026-05-15 13:20

**Actions:**
- Tightened ADR §2 with a new assumption about data-plane vs. control-plane anomaly emission (the question that came up during Phase 3 end-to-end testing: a fault triggered via `POST /vehicles/{id}/status` produces a maintenance record but no anomaly row — that's by design, anomalies fire only on the telemetry-ingest path).
- Trimmed the new bullet to keep the ADR at 824 words (close to the 800 target — one rendered page).
- Wrote `README.md`: prerequisites, run commands, hand-test curls, load-smoke instructions, where to find each artifact.
- Wrote this reflection section (below).
- Initialized the git repo (next step).

**Manual verification:** Re-read the final ADR top to bottom. Each claim still matches the code: SQLite WAL ✓, single concurrency story (UPDATE arithmetic + BEGIN IMMEDIATE + GROUP BY snapshot) ✓, four anomaly rules with the stated thresholds ✓, "significantly = 100× vehicles / 10× frequency" ✓.

---

## Phase 4 — verification-runner (general-purpose) — 2026-05-15 13:00

**Prompt:** Walk every line of `checklist.md` against the running system + code. Curl backend endpoints. Read frontend code for browser-only items. Run pytest. Edit `checklist.md` in place — `[ ]` → `[x]` or `[❌]` with a `> note: ...` on each fail. Append a summary block at the bottom.

**Output summary:** 68 ✅ / 7 ❌. All 7 outstanding are Phase 5 deliverables (README, public repo, AI log reflection bullets). Pytest 34/34 pass. Code is feature-complete against the spec.

**Corrections / redirections:** none. The subagent independently confirmed the same three load-bearing facts I had checked manually: zone counter is SQL arithmetic (`routes/telemetry.py:95-102`), fault transition uses BEGIN IMMEDIATE with re-read inside the lock (`routes/status.py:94-156`), fleet state is a single GROUP BY under WAL (`routes/reads.py:117-129`). Independent confirmation of the same loci is a good sign.

**Manual verification:** I had already verified each load-bearing item myself during the earlier phases. This pass is the systematic checklist walk — it catches anything I missed by working at the granularity of "this one feature works" rather than "this one checklist item is satisfied." Nothing new surfaced; that's the desired outcome.

## Phase 3 — frontend-builder (general-purpose) — 2026-05-15 12:30

**Prompt:** Build `frontend/` via `npm create vite@latest frontend -- --template react-ts`. Single page, three components (`VehicleList`, `ZoneCounts`, `AnomalyFeed`), Tailwind via CDN (NOT toolchain), polling at 2 s with `cancelled` flag pattern, plain `fetch` + `useState` + `useEffect`. Also add `GET /vehicles` to the backend (single SELECT, same WAL-snapshot consistency story) since the dashboard needs the 50-vehicle list. Verify the dev server starts and serves the HTML.

**Output summary:** Vite on 5173 (had to add `--host 127.0.0.1` because Vite v8 defaults to IPv6 only), Tailwind CDN injected in `index.html`, backend `GET /vehicles` added + tested (pytest 34/34 — was 33). Three components built with a shared `usePolledJson<T>` hook that takes an optional `onTick` callback to feed the page-level "last updated" clock.

**Corrections / redirections:** None on correctness. One judgment call by the subagent I disagreed with on style: factoring the polling logic into a `usePolledJson` hook instead of repeating the `useEffect` body three times. The brief told them to "use this exact shape," meaning the *pattern*, not "literally inline three copies." Accepted — the hook keeps the cleanup contract in one place. (If I'd specified "inline" I'd push back; I didn't.)

**Manual verification:**
- Read `App.tsx` end-to-end. The polling hook is correct: `cancelled` flag bound by closure, `clearInterval` in cleanup, `onTickRef` to avoid retriggering the effect when the parent's callback identity changes. That `onTickRef` is the kind of detail that's easy to miss — without it the effect would re-register a new `setInterval` on every render of the parent, and you'd get hundreds of intervals after a minute. Subagent got it right unprompted.
- Live end-to-end test: triggered `POST /vehicles/v-10/status` with fault. `GET /fleet/state` went `{moving: 50}` → `{moving: 49, fault: 1}`. `GET /vehicles` row for v-10 shows `status: fault`. Maintenance record visible via direct DB inspection.
- **Subtle but worth recording:** the fault transition produces a maintenance record but does NOT produce a `status_fault` anomaly. That's correct — anomalies fire on the *telemetry-event ingest path* (data plane); the status-update endpoint is the *control plane* and writes the maintenance record as its durable trace. The two paths are intentionally separated. I should consider whether to call this out as an assumption in ADR §2 in Phase 5.

## Phase 2e — orchestrator (self) — 2026-05-15 12:15

**Action:** Wrote `backend/scripts/load_smoke.py` (50 threads, each posting 60 events at 1 Hz over ~60 s = 3,000 events at ~50 RPS, the spec's stated load). Started uvicorn against a fresh DB and ran the script.

**Output summary:**
- Elapsed: 60.8 s. Successes: 3000 / 3000. Errors: 0.
- Fleet state went `{idle: 50}` → `{moving: 50}` cleanly (every vehicle's last event had `status="moving"`).
- Zone delta sum: 293 (every event randomly chose `zone_entered` with 10% probability; the 293 client-side draws matched the 293 server-side increments **exactly**). All 20 zones got hits.
- Anomalies: 0 — correct for this simulator's parameters (no overspeed, no >20 pp battery drop event-over-event, no error codes, no fault). The anomaly path is exercised by the unit + integration tests; this script's job is write-path correctness under sustained load.

**Snag, fixed:** First uvicorn start failed because Docker/Cursor are bound to port 8000 on this machine. I parameterized `BASE_URL` via `TELEMETRY_URL` env var and used port 8765. **Did not kill any existing process** — those bind to ports the user owns. Lesson: in the README, default to 8000 but document the env var override.

**Manual verification:**
- 60.8 s for 3,000 events = ~49 RPS sustained. Matches the spec's 1-Hz-per-vehicle promise.
- The 293-events-vs-293-increments match is what I actually cared about: client-side and server-side counters agreed at the event level under real-shape concurrent load. Combined with the 200-concurrent canary test, that's two independent pieces of evidence the zone counter is correct.

## Phase 2d — read-endpoints-builder (general-purpose) — 2026-05-15 12:00

**Prompt:** Build `GET /anomalies` (vehicle_id + from_/to + limit, default 1h window when both absent), `GET /fleet/state` (single GROUP BY, always returns all 4 statuses), `GET /zones/counts` (single SELECT, always returns all 20 zones). 10 tests covering empties, filters, time window, limit clamp.

**Output summary:** 33/33 pass. Endpoints are single-statement reads against the WAL snapshot — naturally consistent under concurrent writes.

**Corrections / redirections:** none. The subagent kept `from_` as `Optional[str]` rather than parsing to datetime (sensible — column is ISO text, parsing+reformatting would risk format drift). Accepted with a nod.

**Manual verification:**
- Read `reads.py`. SQL for `/fleet/state` is exactly `SELECT status, COUNT(*) AS cnt FROM vehicles GROUP BY status` — one statement, no app-side aggregation. ✓
- The "default 1h window ONLY when both bounds absent" branch is correct: if caller passes only `from`, we trust them and do not synthesize a `to`. Matches ADR §2.
- Both `/fleet/state` and `/zones/counts` fill in zero-value keys defensively — graders running an empty DB will get all 4 statuses and all 20 zones in the response shape rather than a partial dict. Nice belt-and-suspenders.

## Phase 2c — status-transition-builder (general-purpose) — 2026-05-15 11:35

**Prompt:** Build `POST /vehicles/{vehicle_id}/status`. Non-fault path: single UPDATE bumping `status_version` arithmetically. Fault path: open a dedicated `db.SessionLocal()` session, issue `BEGIN IMMEDIATE` as the first statement, re-read `vehicles.status` *inside* the lock, short-circuit-and-commit if already `fault` (idempotent), else UPDATE vehicle + UPDATE active mission + INSERT maintenance_record + COMMIT. Tests including the 10-concurrent canary. Critical guidance: NO Python-level lock for correctness; the lock is `BEGIN IMMEDIATE` + the in-lock re-read.

**Output summary:** 23 tests pass. Concurrent test on `v-02`: 10 parallel fault POSTs → `status="fault"`, `status_version=1`, exactly 1 cancelled mission, exactly 1 maintenance record. Idempotency holds.

**Corrections / redirections:** none on first pass. The subagent followed the BEGIN IMMEDIATE pattern exactly. (Looking back, the brief was very explicit — including the comment block to paste — which deliberately closed the design space. That's the second time tight constraints produced clean code.)

**Manual verification:**
- Read `routes/status.py` end-to-end. Confirmed:
  - `from app import db` then `db.SessionLocal()` — test monkeypatch reaches it. ✓
  - `BEGIN IMMEDIATE` is the FIRST statement on the new connection. No prior SELECT on this session would hold a reader snapshot. ✓
  - The status re-read inside the lock guarantees writer #N+1 sees the flip from writer #N. ✓
  - Idempotent path issues `commit()` (not rollback) — releases the writer lock cleanly so the next contender doesn't busy-wait its full timeout. Small but real win on the 10-concurrent test. ✓
  - `status_version = status_version + 1` arithmetic in SQL, same pattern as the zone counter — never read-modify-write. ✓
- Cross-checked against the ADR §1 sentence: "two concurrent fault writes for the same vehicle serialize cleanly and the second sees the cancelled mission." Implementation matches the claim.

## Phase 2b — ingestion-builder (general-purpose) — 2026-05-15 11:10

**Prompt:** Implement `app/anomaly.py` (full evaluator with the four rules + threadsafe last-event cache), `app/routes/telemetry.py` (POST /telemetry accepting single OR array body, atomic per-event: insert TelemetryEvent → upsert Vehicle (no `status_version` bump) → if zone_entered: `UPDATE zone_counts SET entry_count = entry_count + 1 WHERE zone_id = :z` → anomaly.evaluate + insert rows → commit once per request), test suites for anomaly unit + ingestion HTTP including the **canary 200-concurrent zone counter test**. Critical guidance: arithmetic in SQL, never Python read-modify-write; no per-route threading.Lock; if locked, do not paper over with locks — fix the SQL.

**Output summary:** 18 tests pass (anomaly 6 + ingestion 9 + smoke 3). `charging_bay_1.entry_count == 200` after 200 concurrent posts on a 32-worker pool. Zone-counter test uses `session.expire_all()` to bust identity-map cache before the count check.

**Corrections / redirections:** none on first pass. The subagent stayed inside the brief — no Python lock around the increment, arithmetic in SQL.

**Manual verification (this is the linchpin phase, so I verified by hand):**
- **Opened `routes/telemetry.py` line 95–102**: the increment is literally `UPDATE zone_counts SET entry_count = entry_count + 1 WHERE zone_id = :z`. No read, no python-side `+= 1`. Confirmed.
- **`session.execute` returns a `Result`, `result.rowcount`** is used to detect unknown zones. Verified that path logs a warning and does NOT raise — a typoed zone won't 500 a 100-event batch. Confirmed against `test_unknown_zone_logged_but_not_error`.
- **Anomaly cache update is gated on `curr_ts > existing["timestamp"]`** — out-of-order events don't poison the prior. Solid call by the subagent (beyond the brief but correct).
- **`evaluate()` snapshots the prior dict under the lock then reads outside the lock** — avoids holding the lock during string formatting / list append. Fine for correctness, marginally better for contention.
- **Read the 200-concurrent test**: 200 events fired via `ThreadPoolExecutor(max_workers=32)`, all asserted 202, then ZoneCount queried with `expire_all()` first, asserted `entry_count == 200`. This is exactly the right test shape. The `expire_all()` is genuinely necessary — without it the assertion can read a stale identity-map snapshot from before the concurrent writes landed.

## Phase 2a — backend-scaffolder (general-purpose) — 2026-05-15 10:45

**Prompt:** Build FastAPI skeleton at `backend/` with exact layout, requirements.txt with version ranges, SQLAlchemy 2.x sync engine, WAL pragmas via `@event.listens_for(Engine, "connect")`, six models (TelemetryEvent, Vehicle, Anomaly, ZoneCount, Mission, MaintenanceRecord), `init_db()` that idempotently seeds 20 zones + 50 vehicles + 50 active missions, route stubs only (no real endpoints yet — those are Phase 2b/2c/2d), three smoke tests (healthz, 20-zone seed, 50-vehicle+50-mission seed). No async, no Alembic, no Dockerfile, no README.

**Output summary:** Tree matches the spec. WAL pragmas applied per connection. `init_db()` uses `INSERT OR IGNORE` for zones/vehicles and a COUNT-then-INSERT pattern for missions. All 3 smoke tests pass (0.08s). Two deprecation warnings about `@app.on_event("startup")` — non-blocking.

**Corrections / redirections:** none on first pass. The subagent added a `session` pytest fixture beyond the brief, which is reasonable — the brief required test 2/3 to "open a session" without specifying plumbing, and the added fixture reuses the monkeypatched DB cleanly. Accepted.

**Manual verification:**
- Read `db.py` end-to-end. Confirmed WAL/synchronous/foreign_keys/busy_timeout pragmas execute on every connect. Confirmed `get_session()` rolls back on exception. Confirmed `DB_PATH` resolves to `backend/telemetry.db` from `__file__`.
- Read `models.py`. All six tables present. `ZoneCount.zone_id` is the PK with `entry_count` default 0 — the row exists pre-seeded so `UPDATE zone_counts SET entry_count = entry_count + 1 WHERE zone_id = :z` will hit a real row (zero rows updated = silent drop, which would be the most painful zone-counter bug; pre-seeding eliminates the class).
- Read `tests/conftest.py`. Note: tests monkeypatch `db_module.engine` and `db_module.SessionLocal`. This works for `get_session()` because Python resolves `SessionLocal` from module globals at call time. **Pre-emptive guidance for Phase 2b:** route handlers that need a session outside `Depends` (e.g., a background-style thread) must `from app import db; db.SessionLocal()` — NOT `from app.db import SessionLocal` — or the test monkeypatch won't reach them. Will note in the next brief.

## Phase 1 — adr-drafter (general-purpose) — 2026-05-15 10:15

**Prompt:** Write `ADR.md` from `decisions.md` + `ambiguities.md`. ≤800 words, four fixed section headings, no hedging (banned phrase list), no spec restatement, ≥5 assumptions in section 2, "significantly" defined as 100× vehicles or 10× frequency in section 3, ≥5 omissions in section 4, present-tense declarative tone, no Postgres recommendations.

**Output summary:** 786 words. Section 1 picks SQLite-WAL, the unified per-hot-spot concurrency story (UPDATE arithmetic + BEGIN IMMEDIATE + GROUP BY snapshot), and the four-rule anomaly definition. Section 2 lists 7 assumptions including all required (thresholds, mission seed, timestamps, batch ingest, recent-window). Section 3 names SQLite single-writer, single uvicorn worker, in-memory last-event cache as what breaks first. Section 4 lists 9 omissions.

**Corrections / redirections:** none on this draft — the prompt constraints were tight enough that the output matched. (Compare to Phase 0 where I had to override Postgres recommendations.) This is the difference between "draft me an ADR" and "draft me an ADR with these 10 hard constraints + the locked-decisions file."

**Manual verification:**
- Grep'd for the banned hedging phrases — clean.
- Cross-checked every claim against `decisions.md`: SQLite-WAL ✓, anomaly thresholds (20pp / 5 m/s / non-empty error_codes / status=fault) ✓, single uvicorn worker ✓, 2 s polling ✓.
- Section 1's claim "the second [concurrent fault writer] sees the cancelled mission" is correct under `BEGIN IMMEDIATE` + WAL semantics, but it implies the **implementation must re-read `vehicles.status` inside the locked transaction and bail if already `fault`** — otherwise we'd get duplicate maintenance records. Flagged for Phase 2c. The ADR statement holds; the code has to honor it.

## Phase 0 — spec-analyst (general-purpose) — 2026-05-15 09:55

**Prompt:** Read SPEC.md end to end, produce `checklist.md` (every concrete deliverable as a binary checkbox, grouped under 10 fixed headers, granular enough that "POST /telemetry exists" and "POST /telemetry validates payload shape" are separate items) and `ambiguities.md` (every place the spec is deliberately open, with the decision space and a one-sentence ADR draft for each).

**Output summary:** Clean extraction — 60+ checklist items across 10 sections, 12 ambiguities. Identified the spec-relevant hot spots: framework choice, DB choice, anomaly definition, fault isolation, zone-counter mechanism, aggregate-state safety, polling vs. WS, "significantly" for scale, batch vs. single payload, anomaly "recent" window, the unspecified mission model, and timestamp format.

**Corrections / redirections:**
- **Postgres recommendation in #2, #4, #5, #6 — overridden.** The subagent leaned Postgres on the concurrency story. My locked decision is SQLite + WAL. Reason it got it wrong: it pattern-matched "correct under concurrent writes" → "needs MVCC + row locks" without weighing the load (50 RPS, not 5,000) or the ops cost of Postgres in a take-home. The mechanisms it proposed (atomic UPDATE arithmetic, single GROUP BY, transaction-wrapped fault path) are still correct — just under SQLite's serialized-writer model instead of row locks.
- **Single-only ingest payload in #9 — overridden.** The spec's example shows two events back-to-back; accepting an array is trivial inside the same transaction; the cost of supporting both is one isinstance check. Rejected the subagent's "single only" framing.

I edited `ambiguities.md` to add a header that flags which items are superseded by `decisions.md` rather than rewriting the file — preserves the raw extraction as evidence of what the AI suggested vs. what I shipped.

**Manual verification:** Read both files top to bottom against SPEC.md. Confirmed:
- Checklist covers all 7 backend deliverables, all 4 frontend deliverables, all 4 ADR sections, all 4 AI-log requirements, and the submission requirements. No spec sentence is unrepresented.
- The 20 zone IDs are listed verbatim (checked against SPEC.md lines 75–96 — exact match).
- Ambiguities #1, #3, #7, #8, #10, #11, #12 are genuine open questions; #2, #4, #5, #6, #9 are now superseded but the *space* of the decision is still valid for the ADR's section 2 narrative.

---

## Reflections

**Where AI was strongest.** The clearest wins were on bounded, well-specified tasks where the brief left almost no design choices: scaffold-this-tree (Phase 2a), implement-this-handler-with-this-SQL (Phase 2b ingestion and 2c fault transition), and run-this-checklist (Phase 4). When the brief named the SQL strings, the lock semantics, and the test shapes, the subagents produced code that compiled, ran, and passed the canary tests on first attempt. Three of the six implementation phases needed zero redirection — that's a very different experience from "write me an ingestion endpoint" with no constraint scaffolding.

**Where AI was confidently wrong.** The Phase 0 spec-analyst recommended Postgres in four of twelve ambiguity entries, despite the locked decision being SQLite. It pattern-matched "correct under concurrent writes" to "needs MVCC + row locks" without weighing the actual load (50 RPS) or the ops cost of running Postgres in a take-home. The mechanisms it suggested (atomic UPDATE arithmetic, single GROUP BY, transaction-wrapped fault path) were still correct under SQLite's serialized-writer model — it had the right shape, wrong engine. I had to override the engine choice explicitly and preserve the analyst's text with a header noting which items were superseded. Lesson: when you have already made a locked decision, *tell the subagent that decision is locked* in the prompt. Don't ask it to "consider" or "evaluate" — it will confidently re-derive a different answer.

In the QA phase, the functional-qa agent reported a P0 bug — "GET /anomalies time-range filter is ignored" — that was actually a tester error: the agent queried with `?from_ts=…&to_ts=…` (invented param names) instead of the endpoint's actual `?from=…&to=…` aliases. FastAPI silently drops unknown query params and applies the default 1h window, so the agent's queries all looked identical. I reproduced with correct param names and confirmed the filter works. Lesson: an AI's "I found a P0" deserves the same skepticism as its "this works" — if anything more, because P0 claims trigger downstream firefighting.

**What I had to verify manually because I didn't trust the AI's first answer.** Four things, all where the wrong assumption would have caused silent failures:
1. The zone-counter SQL — I opened `routes/telemetry.py` and read the literal `UPDATE zone_counts SET entry_count = entry_count + 1 WHERE zone_id = :z` to confirm the arithmetic is in SQL, not Python read-modify-write. The 200-concurrent test passing on first try was suggestive but not conclusive — a Python `+= 1` under a `threading.Lock` could pass that test for the wrong reasons. Reading the SQL is the actual evidence.
2. The fault-transition `BEGIN IMMEDIATE` placement — I confirmed it is the first statement on a fresh `db.SessionLocal()` connection (not the request-scoped one that already issued a SELECT). Easy to get wrong if the subagent had just sprinkled `text("BEGIN IMMEDIATE")` into the existing handler; that would not have acquired the writer lock cleanly.
3. The `usePolledJson` hook's `onTickRef` pattern — I confirmed the polling effect depends on `[path]` only, not on the callback identity, otherwise every parent re-render would register a fresh `setInterval` and pile them up unboundedly.
4. The alleged time-filter P0 — see the "confidently wrong" paragraph above. Reproducing with correct param names took 30 seconds and saved an unnecessary backend change.

**Net time vs. solo.** Hard to be precise, but my honest estimate is that the AI saved roughly 60–70% of the implementation time and added back roughly 15% in oversight overhead (writing tight prompts, reading code to verify correctness, logging redirections). The net is favourable, but only because I treated the subagents as smart-but-loose pair programmers, not as autonomous workers. Two of the strongest correctness wins (the canary tests for the zone counter and the fault transition) came from the prompts naming the test shape and the failure-mode-to-not-cover (e.g., "do NOT add a Python-level lock — fix the SQL instead"). When those guardrails were in the prompt, the output was clean; the one phase where I hedged my guardrails (Phase 0 spec-analyst, where I asked for "decision space" rather than locking the choices upfront) was the one that produced confidently wrong recommendations.

**What the QA phase caught that I'd have missed.** The parallel-QA-then-aggregate pattern caught two things my own walkthrough did not: (a) the AI log's Reflections-not-at-end placement (a literal reading of the spec's "at the end" that I'd interpreted as "after the most recent entry"), and (b) the mobile-viewport overflow at 375 px — which I'd never have checked because the demo is at 1440 px. Both got triaged correctly (P1 fix, P2 defer). What the QA phase OVER-reported was the alleged time-filter P0 — confidently wrong, salvaged by 30 seconds of manual reproduction. Net: 2 real findings, 1 false alarm, ~25 min of parallel agent time vs. probably 60+ min of solo manual walking. Worth it, but only because I treated the QA reports as claims-needing-verification, not as findings-needing-fixes.

**Single biggest takeaway.** AI subagents are excellent at *writing* code that meets an explicit contract and terrible at *deciding what the contract should be* — and the same asymmetry holds for QA: they are excellent at running a defined check and reporting numbers, terrible at distinguishing "the system is broken" from "I queried it wrong." The deliverable here would be substantially worse if I had delegated the four locked decisions (SQLite vs. Postgres, polling vs. WS, anomaly definition, framework) to a subagent and asked it to "choose well." Locking those four decisions myself and pinning the per-phase contracts in the prompts is what produced clean code on first attempt for most phases. The locks-first pattern is the lesson I'd take to the next project.

