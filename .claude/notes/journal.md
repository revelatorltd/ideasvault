# Journal

One line per completed unit, newest last. Dates are UTC.

- 2026-08-25 — `ccaa0e2` Baseline imported from owner's zip: 23 files, spec set verbatim, exec bit set on `scripts/publish.sh`. Verified boot on pinned deps.
- 2026-08-25 — `0d9acc6` M0.1 orientation: 4 of 5 prior-session findings confirmed, 1 withdrawn (F3), 1 new found (F6, reindex 500s on deleted DB). SPEC 2.2 exemption for `revision`, SPEC 6 + 7.14 reworded, PLAN task 2.0 added.
- 2026-08-25 — Protocol adopted. `~/.claude/settings.json` created with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (user-level, effective next session).
- 2026-08-25 — Orientation phase: `.claude/notes/orientation.md` written; independent 7-area map + adversarial verify workflow launched. `tests/conftest.py` committed as groundwork only — no test file yet, so `pytest` collects nothing until unit 1.
- 2026-08-25 — U1 test suite: 43 tests (21 metadata + 22 app) covering all 14 SPEC §7 requirements plus F1/F2/F4/F6 guards. 39 pass; the 4 failures are exactly the known defects. `requirements-dev.txt` added (pytest, httpx — httpx forced by PLAN M1.1's mandated `fastapi.testclient`). Runtime deps still five. No `app/` code touched.
