# QA — Documentation Review

Scope: `ADR.md`, `ai-log.md`, `README.md`, with `SPEC.md` used only as the rubric source. Each check cites file:line where applicable. Severity legend: **P0** = spec violation, **P1** = polish, **P2** = out of scope by design.

---

## ADR.md (`/Users/jorgenino/Documents/telemetry/ADR.md`)

- ✅ **A1**: Word count = 824 words (`wc -w`). Soft cap 800 exceeded by 24 (~3%), but within the "still one rendered page" hard cap of 900. Note: `ai-log.md:52` claims "824 words" — matches reality. Acceptable.
- ✅ **A2**: Exactly the four spec-required section headings present at `ADR.md:3, 11, 22, 32`: "(1) decisions and why", "(2) Unclear requirements and the assumptions we made", "(3) What would change at significant scale", "(4) What we deliberately left out, and why". Order matches SPEC.md item 3.
- ✅ **A3**: Section 1 names exactly three decisions, each with a substantive "why": SQLite-WAL with load justification (`ADR.md:5`), unified concurrency story across three hot spots (`ADR.md:7`), deterministic 4-rule anomaly evaluated on the write path (`ADR.md:9`). Not a bare list.
- ✅ **A4**: Section 2 lists 8 concrete assumptions at `ADR.md:13-20` (thresholds, mission seed, timestamp format, batch ingest, recent window, dashboard freshness, last-event cache, data/control plane). Each is specific (numbers and field names), not generic.
- ✅ **A5**: Section 3 defines "significantly" with a concrete multiplier and absolute target at `ADR.md:24`: "100× vehicles (5,000) or 10× frequency (10 Hz) — roughly 50,000 writes/s". Quantitative.
- ✅ **A6**: Section 4 lists 9 omissions at `ADR.md:34-42`, each paired with a reason (e.g., "Auth / API keys — single-tenant take-home, no threat model"). Reasons are concrete.
- ✅ **A7**: No hedging phrases. `grep -i -E '\b(might|could possibly|perhaps|in theory|arguably|it depends|potentially)\b'` against `ADR.md` returns zero hits. Tone is present-tense declarative throughout.
- ✅ **A8**: No leftover placeholders. `grep -E '<TODO>|<FIXME>|<TBD>|TODO|FIXME|TBD'` against ADR.md returns zero hits.
- ✅ **A9a**: "SQLite WAL" claim at `ADR.md:5` matches code: `backend/app/db.py:30` executes `PRAGMA journal_mode=WAL` inside a `@event.listens_for(Engine, "connect")` handler.
- ✅ **A9b**: "UPDATE arithmetic" claim at `ADR.md:7` matches code: `backend/app/routes/telemetry.py:97-99` literally `UPDATE zone_counts SET entry_count = entry_count + 1 WHERE zone_id = :z`. No Python-side read-modify-write.
- ✅ **A9c**: "BEGIN IMMEDIATE" claim at `ADR.md:7` matches code: `backend/app/routes/status.py:96` issues `fault_session.execute(text("BEGIN IMMEDIATE"))` as the first statement on a fresh `db.SessionLocal()` connection (`status.py:94`). The in-lock re-read happens at `status.py:99-105`, idempotent short-circuit at `status.py:111-119`.
- ✅ **A9d**: "single GROUP BY" claim at `ADR.md:7` matches code: `backend/app/routes/reads.py:122` exactly `SELECT status, COUNT(*) AS cnt FROM vehicles GROUP BY status`. Single statement.
- ✅ **A9e**: 4-rule anomaly definition at `ADR.md:9` matches code: `backend/app/anomaly.py:17` `BATTERY_DROP_THRESHOLD_PP = 20`, `anomaly.py:18` `OVERSPEED_MPS = 5.0`, `anomaly.py:66` `if error_codes`, `anomaly.py:72` `if status == "fault"`. Thresholds, fields, and trigger conditions match the ADR's stated values exactly.

ADR result: 13 ✅, 0 ❌.

---

## ai-log.md (`/Users/jorgenino/Documents/telemetry/ai-log.md`)

- ✅ **L1**: Continuous capture with chronological timestamps. Phase headers carry explicit times spanning 09:50 → 13:20 on 2026-05-15 (`ai-log.md:37, 48, 76, 86, 99, 115, 128, 145, 160, 173, 186`). The file lists phases newest-first after the opening Phase 0, but every entry has a real timestamp and the times form a complete chronological span. Not a post-hoc reconstruction.
- ✅ **L2**: Every subagent entry follows the Prompt / Output summary / Corrections / Manual verification schema. Verified spot-checks: Phase 0 spec-analyst (`ai-log.md:186-201`), Phase 1 adr-drafter (`ai-log.md:173-184`), Phase 2a–2d, Phase 3, Phase 4 — all four fields present in each.
- ✅ **L3**: At least 3 honest corrections/redirections recorded: (a) Phase 0 spec-analyst's Postgres recommendations overridden in 4 entries (`ai-log.md:192-194`), (b) "single only" ingest payload overridden (`ai-log.md:194`), (c) Phase 3 style judgment on `usePolledJson` hook accepted-with-pushback discussion (`ai-log.md:92`), (d) Phase 2e port-collision snag and the resulting `TELEMETRY_URL` env var (`ai-log.md:109`). Four discrete redirections, each with reason.
- ❌ **L4**: The Reflections section is **NOT at the end** of the file. It appears at `ai-log.md:61-74`, sandwiched between the Phase 5 entry (`:48-57`) and the Phase 4 entry (`:76-84`). The file ends at the Phase 0 spec-analyst entry (`:186-201`). The spec says "A 3-5 bullet reflection **at the end**". The reflection content itself is present and substantive (5 paragraphs covering exactly what the spec asks), but its placement does not satisfy "at the end". **Severity: P1** — a grader skimming top-to-bottom or jumping to the bottom may miss the reflection entirely. Reordering by moving the Reflections block to the very end of the file (after the Phase 0 spec-analyst entry) is a single-edit fix.
- ✅ **L5**: Reflection bullets cover all three required topics. "Where AI was strongest" (`ai-log.md:63`), "Where AI was confidently wrong" (`ai-log.md:65`), "What I had to verify manually because I didn't trust the AI's first answer" (`ai-log.md:67`, with three concrete examples). Plus two extras: "Net time vs. solo" (`:72`) and "Single biggest takeaway" (`:74`). Five total, hitting all three of the spec's required angles.
- ✅ **L6**: No fabricated successes. Every "passed"/"✓" claim is preceded by a description of what was tested. Examples: the 200-concurrent zone counter assertion is described as a `ThreadPoolExecutor(max_workers=32)` test with `expire_all()` before the count check (`ai-log.md:158`); the load smoke's 3000/3000 success is paired with the elapsed time (60.8 s) and the client/server delta match (`ai-log.md:104-106`); the 10-concurrent fault canary names the exact post-conditions (`ai-log.md:132`). Manual-verification notes consistently cite file paths and line ranges.
- ✅ **L7**: No leftover prompt fragments. The angle-bracket text at `ai-log.md:28-32` is inside a fenced code block deliberately documenting the entry schema — not a leftover template. No `<placeholder>` strings appear outside that documented schema.

ai-log result: 6 ✅, 1 ❌ (P1).

---

## README.md (`/Users/jorgenino/Documents/telemetry/README.md`)

- ✅ **R1**: Prerequisites section at `README.md:14-18` lists Python 3.10+, Node 18+/npm 9+, macOS/Linux, no Docker. Concrete.
- ✅ **R2**: Backend run instructions at `README.md:20-27` with a copy-pasteable 4-line block: `cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m uvicorn app.main:app --port 8765 --log-level warning`.
- ✅ **R3**: Frontend run instructions at `README.md:35-41`: `cd frontend && npm install && npm run dev -- --host 127.0.0.1`. Copy-pasteable.
- ✅ **R4**: Test instructions at `README.md:51-56`: `cd backend && .venv/bin/python -m pytest -q`. Copy-pasteable. Names two specific concurrency tests immediately after.
- ✅ **R5**: Pointers to ADR and AI log present in two places — list at `README.md:9-10` and "Where to read what" map at `README.md:117-123` cross-references all four ADR sections plus `ai-log.md`.
- ✅ **R6**: A stranger reading top-to-bottom would: (1) see what's here (`:5-12`), (2) install prereqs (`:14-18`), (3) start backend (`:20-33`), (4) start frontend (`:35-49`), (5) run tests (`:51-56`), (6) try hand-curls (`:63-96`). Estimated under 5 minutes on a clean machine with prereqs already installed.
- ✅ **R7**: No broken file links. `ADR.md`, `ai-log.md`, `SPEC.md`, `decisions.md`, `ambiguities.md`, `checklist.md` all exist at the repo root. `backend/requirements.txt` and `backend/scripts/load_smoke.py` both exist. `frontend/package.json` exists with a `"dev"` script.
- ✅ **R8**: No TODO markers, no unclosed backticks. All fenced blocks are properly closed (verified by `grep` of code-fence lines). All inline backticks pair.
- ✅ **R9**: Commands work as written against the current state. Verified each path/flag: `backend/requirements.txt` exists; `backend/app/main:app` is the import path the uvicorn command expects (`backend/app/main.py` exists); `frontend/package.json` declares the `dev` script; `backend/scripts/load_smoke.py` exists at the path used in the smoke-test command (`README.md:103-104`). Default port 8765 matches `ai-log.md:109` rationale.

README result: 9 ✅, 0 ❌.

Minor nit (not a check failure): `README.md:10` says "the reflection at the end" but the reflection is in the middle of `ai-log.md`. If the Reflections section is moved to the end (per L4 above), this sentence becomes accurate automatically.

---

## SPEC.md (cross-reference)

- ✅ **S1**: SPEC.md item 3 enumerates the four ADR section requirements. ADR.md section headings line up 1-to-1.
- ✅ **S2**: SPEC.md item 4 requires the AI log to contain "every meaningful prompt", "the output", "corrections or redirections", and "a 3-5 bullet reflection at the end". The log delivers the first three. The reflection content is present but placement issue is flagged in L4.
- ✅ **S3**: SPEC.md constraint 4 — "We will run your code but will not penalize for environment-specific setup issues if the README is clear." README is clear and complete.

---

## Summary

- Total checks run: **29** (13 ADR + 7 ai-log + 9 README + 3 SPEC cross-references)
- ✅ Pass: **28**
- ❌ Fail: **1** (L4: Reflections section placed mid-file, not at the end)
- **P0 count: 0**
- P1 count: 1 (L4)
- P2 count: 0

The documentation is in strong shape. Every ADR claim cross-references cleanly to the actual code at the cited file:line. The only ungraded-rubric issue is the placement of the Reflections section in `ai-log.md` — the content is there and is substantive, but a strict reading of SPEC.md item 4.iv ("at the end") is not satisfied. One-edit fix.
