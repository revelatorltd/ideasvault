# Plan — ship Ideas Vault without bugs

Ordered checklist. Units are independent unless a dependency is stated. Each has a
verification command that must pass in the transcript before its box is ticked.

Defect IDs (F1–F6) are defined in `.claude/notes/orientation.md`.

---

## U1 — Test suite covering SPEC §7

There is currently no test suite at all, so nothing below can be verified safely
until this exists. Covers all 14 requirements in SPEC §7 plus regression guards for
F1, F2, F4 and F6. Adds `requirements-dev.txt` (pytest only — the runtime five stay
five and the Dockerfile does not ship it).

**No `app/` code is modified in this unit.** Tests are written against the spec, so
the F1/F2/F6 tests are expected to fail here and go green in U2–U4. That is the
point: the suite must detect the known defects.

- [x] **Verify:** `pytest -q` collects ≥20 tests, and the *only* failures are the
  named F1/F2/F6 regression tests. Any other failure means the suite itself is wrong.
  **Done:** 43 tests, 39 passed, 4 failed — exactly `test_7_6` (F2), `test_F1` (F1),
  `test_F4` (F4) and `test_7_11` (F6). Identical across three consecutive runs.
  Note: F4 also got a guard here, so U4 is covered by the suite too.

## U2 — Fix F6: `reindex` cannot rebuild a deleted index

`POST /api/reindex` raises `sqlite3.OperationalError: no such table: ideas` and 500s
when `vault.db` has been deleted, because `db.init()` runs only in the boot lifespan.
This is invariant 1's headline promise and SPEC §7 test 11.

Smallest fix: make the schema self-healing rather than boot-dependent. Must not add a
second write path (invariant 2).

- [x] **Verify:** `pytest -q -k "reindex or invariant1"` exits 0, and by hand:
  publish, delete `$VAULT_DB`, `POST /api/reindex` → 200 with every row restored.
  **Done.** `test_7_11`, `test_F6_*` and `test_F7_*` pass. By hand: `GET /` 200
  after deleting `vault.db` (was 500), `POST /api/reindex` → `{"indexed":2}`,
  both titles restored.

  Scope grew twice during this unit, both confirmed by probe:
  - **F6 was wider than SPEC §7.11.** `list_ideas` and `get` raised too, so
    `GET /` and `GET /i/{slug}` also 500'd after a DB deletion. Fixed at
    `db.conn()` — every connection now ensures the schema, because the index is
    disposable and the file can vanish mid-process. A once-per-process flag
    would not survive exactly the scenario the test covers.
  - **F7 (new): `reindex` was not total.** It only inserted, so a row whose
    artifact was deleted outside the app survived forever — making `/raw/`'s
    410 "Run POST /api/reindex" advice impossible to follow. Added `db.prune()`;
    reindex now drops rows with no file. Verified: 410 → reindex → 404.

## U3 — Fix F1 + F2: `revision` counts content changes, not writes

Per the owner's decision (SPEC §2.2 exemption): only a changed `sha256` bumps
`revision`. `reindex` preserves it; a byte-identical republish preserves it. This is
what makes `reindex` idempotent, which matters more than the counter.

Depends on U2 (both touch the same `db.upsert` / `ingest.publish` seam).

- [x] **Verify:** `pytest -q -k revision` exits 0. Explicitly: a changed body gives
  `revision` 2 (SPEC §7.4); identical bytes stay at 1 row and the same revision
  (§7.6); two consecutive reindexes leave every revision untouched.
  **Done.** Both defects had one root cause, so one rule fixed both: only a
  changed `sha256` bumps. Measured — new → 1, identical → 1, changed → 2,
  three reindexes → still 2. `updated_at` is also left alone on a no-op, which
  matters because `list_ideas` orders by `date DESC, updated_at DESC`: had
  reindex kept touching it, card order would have shuffled on every rebuild.

## U4 — Fix F4: slug collision guard is narrower than SPEC §2.4

`ingest.py` ANDs an on-disk sha check onto the spec's condition, so a stale or
rebuilt index can let `dest.write_bytes` overwrite a different artifact — the one
loss invariant 1 exists to prevent.

- [x] **Verify:** `pytest -q -k collision` exits 0, including the stale-index case:
  a row whose `sha256` differs from a same-named file on disk must not be overwritten.
  **Done.** `pytest -q` → **45 passed, 0 failed.** The fix made the guard
  *simpler*: it now keys on the file, dropping the `db.get` entirely, because
  disk is truth and a disposable index must never license an overwrite.
  Measured: row dropped + same title + different content → `shared-2a3535`,
  original intact; forced 6-char suffix collision escalates to 12
  (`shared-3a924609ffa5`) leaving the squatter intact; byte-identical republish
  with no explicit slug adds no file. If even the full digest is taken by
  different bytes it now refuses with a 400 naming the fix, rather than
  overwriting.

## U5 — PLAN task 2.0: clear the pre-M2 blockers

Three fixes outside `app/` logic:
- `docker-compose.yml`: `profiles: ["edge"]` on `tunnel` + a `:?` guard on
  `CF_TUNNEL_TOKEN` (F5) so `docker compose up -d` does not crash-loop it.
- `app/templates/detail.html`: add `Inter` to the font link to match `style.css`.
- `.env.example`: blank the `VAULT_TOKEN` placeholder so a copied-but-unedited file
  fails closed with 503 instead of opening writes on a known token.

- [x] **Verify:** `docker compose config` parses and shows `tunnel` under profile
  `edge` (falling back to a YAML+grep assertion if no Docker daemon is available —
  there is none in this container); `grep Inter app/templates/detail.html` matches;
  `grep -E '^VAULT_TOKEN=$' .env.example` matches.
  **Done.** The compose *CLI* parses without a daemon, so this was verified
  properly rather than by grep:
  - `docker compose config --services` → `vault` only (the M2 path)
  - `docker compose --profile edge config --services` → `vault`, `tunnel` (M3)
  - `docker compose config --profiles` → `edge`
  - empty `VAULT_TOKEN` → rejected, so the blanked `.env.example` fails closed
  - `style.css` wants 3 font families, `detail.html` now loads all 3, gap none

  **My first attempt at this unit introduced a worse bug and the verification
  caught it.** I put a `:?` required-variable guard on `CF_TUNNEL_TOKEN`. Compose
  interpolates every service regardless of active profile, so that made plain
  `docker compose up -d` fail outright at M2 — worse than the crash-loop being
  fixed. Replaced with `:-` and a comment recording why a guard cannot go there.

## U6 — Merge the independent sweep

The orientation workflow mapped all seven areas and adversarially verified each
candidate defect. Any newly *confirmed* defect becomes a numbered unit here with its
own verification command; refuted and unverified claims are recorded in
`orientation.md` rather than silently dropped.

- [x] **Verify:** every confirmed finding either has a ticked unit or an explicit
  written reason for deferral in `orientation.md`.
  **Done, with one caveat stated plainly.** The sweep returned 3 of 7 area maps
  (metadata, db, ingest — 18 candidates) before I had to close out; its
  adversarial-verify phase never ran, because the runner's concurrency cap is 2
  and 14 agents serialise into pairs. So I verified every candidate myself with
  real output instead of relying on it.

  Outcome: it independently rediscovered F6 (wider form), F7 and F12, all
  already fixed; its `notes.html~` finding was already closed by F10. Six new
  defects confirmed and fixed — **F13** (Unicode digits passed the "strict"
  date check), **F14** (non-ASCII explicit slug hashed the body, so one idea
  became two rows — invariant 3), **F15** (non-atomic write could destroy the
  only copy — invariant 1), **F16** (corrupt `vault.db` crash-looped, against
  SPEC §6's promise of automatic recovery), **F17** (racing first publish 500'd),
  **F18** (oversized inbox file read into memory before the size check).

  Two confirmed findings **deliberately not fixed**, both needing an owner
  decision, written up in `orientation.md`: `idea:*` honoured inside `<pre>`
  (an artifact documenting the metadata block can escalate its own visibility),
  and `drain_inbox` reading a file a sync client is still writing.

  The 4 unreturned maps: I covered `main` and `views` in my own adversarial pass
  (token timing, traversal, autoescape, viewer level, poller spam); `ops` was
  covered by U5; `mcp` is PLAN M5.1 and out of scope by this plan's own
  boundaries.

  **UPDATE — the sweep later completed (14/14 agents, 42 candidates).** Its
  verify phase returned 7 verdicts: **6 refuted**, every one a stale re-report of
  a defect I had already fixed (the verifiers name commits `dcf9d87` and
  `2018493`), and **1 confirmed** — F19, below. The cap left **35 candidates
  unverified**; I triaged all 35 by hand.

  - **F19 (confirmed).** `api_publish` was `async def` but ran `ingest.publish`
    inline, so BeautifulSoup cost landed on the event loop. A legal upload under
    `VAULT_MAX_BYTES` was measured at **65s of CPU** (soup 41.9s + first_prose
    8.3s, linear in size), freezing every route including `/healthz` — which the
    M6.3 monitor would read as the vault being down. Now `asyncio.to_thread`,
    the mechanism `watch_inbox` already used.
  - **F20 — a regression from my own F8 fix.** `secrets.compare_digest` raises on
    a non-ASCII `str`, so an unauthenticated caller could turn a 401 into a 500
    with `Authorization: Bearer tökén`. httpx refuses to send such a header,
    which is why the suite missed it; a raw socket does not. Verified against
    uvicorn: **500 before, 401 after**. Now compared as bytes.
  - **F21 — a regression from my own F7 fix.** `prune` deleted every row absent
    from the directory snapshot, so an artifact published *during* a reindex lost
    its row while its file stayed on disk. The inbox poller runs every 3s, so the
    race is routine. Now a row is dropped only if its file is genuinely absent at
    prune time.
  - Also documented `docker compose --profile edge up -d` in the README — my own
    profile change had made it the required M3 command and nothing said so.

  Of the remaining 32 unverified candidates: most restate defects already fixed
  (F6, F7, F9, F10, F12, F14, F15, F17, F18). Genuinely open and **not** actioned,
  all in areas this plan excludes or already flagged: five `mcp/server.py`
  findings (PLAN M5.1, out of scope — the meta-block injector duplicating a block
  and its defaults overwriting an artifact's own visibility look real and serious,
  and should be the first thing M5.1 checks), two `index.html` client-filter
  issues (tags containing spaces break the chip filter; uncapped tag text is
  rendered five times per card), `publish.sh` discarding the API's error body, no
  `overflow-wrap` in the CSS, and the `.gitignore` `inbox/*.htm*` case-sensitivity
  mismatch. None are correctness defects in the shipped write path.

## U7 — Green gate

- [x] **Verify:** `pytest -q` exits 0 with zero failures; run twice, identical
  results (no ordering dependence); `git status --short` empty; PLAN.md boxes for
  1.1, 1.2 and 2.0 ticked.
  **Done** — see the transcript for the final run.

---

## Deliberately not in this plan

Stated rather than silently skipped:

- **PLAN M2.1–2.3 (compose boot, file real artifacts, timing) and all of M3
  (Cloudflare Tunnel + Access).** No Docker daemon and no Cloudflare console in this
  container. U5 removes the known blocker so these are ready to run, but they are the
  owner's to execute and verify.
- **PLAN M4 (sync folder, shell alias), M5.2/M5.3 (connect the MCP connector, write
  the skill), M6.3 (health alert).** All require the owner's machine, phone or
  Cloudflare account.
- **PLAN M5.1 (harden `mcp/server.py`).** In-scope code and testable here, but PLAN
  sequences it after deploy and it is a draft that runs outside the container. Left
  for its own session rather than widened into this one.
- **PLAN M6.1/M6.2 (backups, structured logging).** Later milestone; neither affects
  correctness of the shipped app.
- Everything in the PRD §6 non-goals table and the PLAN Deferred table.
