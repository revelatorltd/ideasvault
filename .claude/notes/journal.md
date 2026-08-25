# Journal

One line per completed unit, newest last. Dates are UTC.

- 2026-08-25 — `ccaa0e2` Baseline imported from owner's zip: 23 files, spec set verbatim, exec bit set on `scripts/publish.sh`. Verified boot on pinned deps.
- 2026-08-25 — `0d9acc6` M0.1 orientation: 4 of 5 prior-session findings confirmed, 1 withdrawn (F3), 1 new found (F6, reindex 500s on deleted DB). SPEC 2.2 exemption for `revision`, SPEC 6 + 7.14 reworded, PLAN task 2.0 added.
- 2026-08-25 — Protocol adopted. `~/.claude/settings.json` created with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (user-level, effective next session).
- 2026-08-25 — Orientation phase: `.claude/notes/orientation.md` written; independent 7-area map + adversarial verify workflow launched. `tests/conftest.py` committed as groundwork only — no test file yet, so `pytest` collects nothing until unit 1.
- 2026-08-25 — U1 test suite: 43 tests (21 metadata + 22 app) covering all 14 SPEC §7 requirements plus F1/F2/F4/F6 guards. 39 pass; the 4 failures are exactly the known defects. `requirements-dev.txt` added (pytest, httpx — httpx forced by PLAN M1.1's mandated `fastapi.testclient`). Runtime deps still five. No `app/` code touched.
- 2026-08-25 — U2 fixed F6 (schema ensured per-connection in `db.conn()`, not just at boot — reads 500'd too, wider than SPEC §7.11) and new F7 (`reindex` only inserted, so stale rows made the 410 advice unfollowable; added `db.prune()`). 42 pass, 3 remaining failures are F1/F2/F4.
- 2026-08-25 — U3 fixed F1+F2 with a single rule in `db.upsert`: only a changed sha256 bumps `revision` (and `updated_at`). Also stops reindex shuffling card order via the `updated_at` sort tiebreaker. 44 pass, 1 remaining failure is F4.
- 2026-08-25 — U4 fixed F4: collision guard keys on the file, not the index row (disk is truth), so a rebuilt index can no longer license destroying an artifact. Suffix escalates 6→12→64 hex and refuses rather than overwrite. Full suite 45/45 green.
- 2026-08-25 — U5 (PLAN 2.0) fixed F5 via `profiles: ["edge"]`, added Inter to detail.html, blanked the .env.example token. First attempt added a `:?` guard on CF_TUNNEL_TOKEN which broke `docker compose up` at M2 entirely (compose interpolates all services regardless of profile) — caught by the unit's own verification and replaced with `:-`. 45/45 green.
