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

- [ ] **Verify:** `pytest -q -k "reindex or invariant1"` exits 0, and by hand:
  publish, delete `$VAULT_DB`, `POST /api/reindex` → 200 with every row restored.

## U3 — Fix F1 + F2: `revision` counts content changes, not writes

Per the owner's decision (SPEC §2.2 exemption): only a changed `sha256` bumps
`revision`. `reindex` preserves it; a byte-identical republish preserves it. This is
what makes `reindex` idempotent, which matters more than the counter.

Depends on U2 (both touch the same `db.upsert` / `ingest.publish` seam).

- [ ] **Verify:** `pytest -q -k revision` exits 0. Explicitly: a changed body gives
  `revision` 2 (SPEC §7.4); identical bytes stay at 1 row and the same revision
  (§7.6); two consecutive reindexes leave every revision untouched.

## U4 — Fix F4: slug collision guard is narrower than SPEC §2.4

`ingest.py` ANDs an on-disk sha check onto the spec's condition, so a stale or
rebuilt index can let `dest.write_bytes` overwrite a different artifact — the one
loss invariant 1 exists to prevent.

- [ ] **Verify:** `pytest -q -k collision` exits 0, including the stale-index case:
  a row whose `sha256` differs from a same-named file on disk must not be overwritten.

## U5 — PLAN task 2.0: clear the pre-M2 blockers

Three fixes outside `app/` logic:
- `docker-compose.yml`: `profiles: ["edge"]` on `tunnel` + a `:?` guard on
  `CF_TUNNEL_TOKEN` (F5) so `docker compose up -d` does not crash-loop it.
- `app/templates/detail.html`: add `Inter` to the font link to match `style.css`.
- `.env.example`: blank the `VAULT_TOKEN` placeholder so a copied-but-unedited file
  fails closed with 503 instead of opening writes on a known token.

- [ ] **Verify:** `docker compose config` parses and shows `tunnel` under profile
  `edge` (falling back to a YAML+grep assertion if no Docker daemon is available —
  there is none in this container); `grep Inter app/templates/detail.html` matches;
  `grep -E '^VAULT_TOKEN=$' .env.example` matches.

## U6 — Merge the independent sweep

The orientation workflow mapped all seven areas and adversarially verified each
candidate defect. Any newly *confirmed* defect becomes a numbered unit here with its
own verification command; refuted and unverified claims are recorded in
`orientation.md` rather than silently dropped.

- [ ] **Verify:** every confirmed finding either has a ticked unit or an explicit
  written reason for deferral in `orientation.md`.

## U7 — Green gate

- [ ] **Verify:** `pytest -q` exits 0 with zero failures; run twice, identical
  results (no ordering dependence); `git status --short` empty; PLAN.md boxes for
  1.1, 1.2 and 2.0 ticked.

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
