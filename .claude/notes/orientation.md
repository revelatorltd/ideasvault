# Orientation — Ideas Vault

Phase 1 of the autonomous protocol. Read-only: no source was edited producing this.

## 1. What the system is

A self-hosted repository for self-contained HTML artifacts. Publishing is "put the
file in a folder." All metadata lives inside the artifact in `<meta name="idea:*">`
tags, so the file is the only thing anyone manages. Single user, no billing, no
sessions; reader auth is at the edge (Cloudflare Access), not in the code.

Five runtime dependencies: fastapi, uvicorn[standard], jinja2, python-multipart,
beautifulsoup4. Python 3.12 per the Dockerfile — **the container running this work
has 3.11.15**, so tests here execute on 3.11. The code is 3.10+ compatible
(`from __future__ import annotations`, `X | None`), so this is a reporting caveat
rather than a defect.

## 2. Module map

| File | Lines | Role |
|---|---|---|
| `app/metadata.py` | 107 | `parse()` → `IdeaMeta`; `slugify()`; the six fallback chains. Never raises (invariant 4). |
| `app/db.py` | 103 | SQLite index: `SCHEMA`, `conn()`, `init()`, `upsert()`, `list_ideas()`, `get()`, `delete()`. |
| `app/ingest.py` | 80 | The single write path: `publish()`, `drain_inbox()`, `reindex()`, `_sha_of()`. |
| `app/main.py` | 139 | 8 routes, `require_token()`, `watch_inbox()` poller, `lifespan()` with boot auto-reindex. |
| `app/templates/index.html` | 104 | Card index + client-side search/tag filter. |
| `app/templates/detail.html` | 29 | Thin chrome over the sandboxed iframe. |
| `app/static/style.css` | 276 | Custom properties, no framework, no build step. |
| `mcp/server.py` | 94 | Draft MCP publish/search server. Runs **outside** the container; needs `fastmcp`+`httpx`, deliberately not in `requirements.txt`. PLAN 5.1 hardens it. |

Config is read into **module-level globals at import time** (`db.DB_PATH`,
`ingest.CONTENT_DIR`/`INBOX_DIR`/`ARCHIVE_DIR`/`MAX_BYTES`, `main.PUBLISH_TOKEN`/
`VIEWER_LEVEL`/`RAW_ORIGIN`/`POLL_SECONDS`). Consequence for testing: patching
`os.environ` after import has no effect — the globals must be patched instead.
`ARCHIVE_DIR` is derived from `INBOX_DIR` at import, so patching `INBOX_DIR` alone
leaves the archive pointing at the old location.

## 3. Verified state of the baseline

Booted on the pinned deps; the following were exercised with real output.

Holding:
- 401 on all three write endpoints without a token; 503 on all three with
  `VAULT_TOKEN` unset (invariant 6).
- `GET /raw/{slug}` returns `content-security-policy: sandbox allow-scripts
  allow-popups allow-forms`, plus `x-content-type-options: nosniff` and
  `cache-control: no-cache`. `detail.html` carries
  `sandbox="allow-scripts allow-popups allow-forms"`. The artifact body appears in
  `/raw/` and **not** in the detail page (invariant 5).
- Same title + different content + no explicit slug ⇒ suffixed slug
  (`same-title`, `same-title-99c5cd`), two rows, two files (SPEC 7.5).
- Inbox drain: `good.html` and `junk.html` published and moved to `_ingested/`;
  `empty.html` failed and stayed in `inbox/` (SPEC 7.14).

## 4. Confirmed defects

Numbering is stable and referenced by `plan.md` and `journal.md`.

**F1 — `reindex()` inflates `revision`.** It calls `db.upsert`, which always takes
the UPDATE branch and does `revision=revision+1`. Observed: a no-op reindex moved an
idea 2 → 3. The deeper problem is that **reindex mutates data**, so it cannot be run
freely — which undercuts invariant 1 more than the counter itself does.

**F2 — byte-identical republish bumps `revision`.** Observed 1 → 2 on identical
bytes, contradicting SPEC 2.4's "no-op update either way". `publish()` computes the
sha but only uses it for the collision guard, never to short-circuit.

**F3 — WITHDRAWN.** A prior session claimed SPEC 7 test 14 was unsatisfiable because
no file is unparseable. False: an **empty** file fails and stays in place. Malformed
HTML publishing is invariant 4 working correctly. SPEC 6 and 7.14 were reworded to
say "empty or oversized" rather than "unparseable". No code change needed.

**F4 — the slug collision guard is narrower than SPEC 2.4.** `ingest.py:32-35` ANDs
an on-disk sha check onto the spec's condition. If the index is stale or was rebuilt
while a file with different content exists, no suffix is applied and
`dest.write_bytes` overwrites it — losing an artifact, the one thing invariant 1
exists to prevent.

**F5 — `docker compose up -d --build` crash-loops `tunnel`.** No `profiles:` key and
no `:?` guard on `CF_TUNNEL_TOKEN`, so it starts three milestones before M3 creates
the tunnel.

**F6 — `POST /api/reindex` 500s when `vault.db` has been deleted.**
`sqlite3.OperationalError: no such table: ideas`, because `db.init()` runs only in
the boot lifespan. **Fails SPEC 7 test 11** and breaks invariant 1's headline
promise. Missed by the prior session because it deleted the DB and *rebooted*, which
does call `init()`.

Smaller, confirmed:
- All routes are GET-only, so `HEAD /raw/…` (and `/healthz`) returns 405. Relevant
  when wiring the 6.3 monitor — configure it for GET.
- `detail.html:9` omits `Inter` from its font link while `style.css:9` sets
  `--body: 'Inter'`, so the detail page silently falls back to `system-ui`.
- `.env.example` ships `VAULT_TOKEN=change-me-long-random-string`. Copied unchanged,
  that leaves writes open on a known token instead of fail-closed 503 (SPEC 4).

## 5. Decisions already taken by the owner

1. **`revision` counts content changes, not writes.** `reindex` preserves it, a
   byte-identical republish preserves it, only a changed sha256 bumps it. SPEC 2.2
   now carries the exemption; the cost is that `revision` resets to 1 on total
   volume loss, which is the DR path where everything else is gone too.
2. **pytest goes in a separate `requirements-dev.txt`**, not `requirements.txt`, so
   the runtime five stay five and the Dockerfile does not ship pytest.

## 6. Constraints that bound any fix

From `CLAUDE.md`: the six invariants; no sixth runtime dependency without asking; no
ORM, Alembic, Redis, build step or CSS framework; errors say what happened *and what
to do*.

From `docs/PRD.md` §6 non-goals — browser editing, comments, in-app multi-user auth,
body full-text search, themes/i18n, LinkFlow merge. All out.

From `docs/PRD.md` §7 assumptions, which **cap the severity of some findings**:
- **A2** artifacts are self-contained; ones pulling from relative `./assets/` break.
  Accepted, not a bug.
- **A3** single author; concurrent publishes are not a real scenario and
  **last-write-wins on a slug is acceptable**. Concurrency findings are therefore
  low severity unless they corrupt the index or lose a file.
- **A5** artifacts under 15 MB; larger rejected with a clear error.

## 7. Independent sweep

An orientation workflow mapped all seven areas (metadata, db, ingest, main, views,
mcp, ops) and adversarially verified each candidate defect — default position that
the claim is wrong, real output required to confirm. Results appended below.

### Found by my own adversarial pass while the workflow ran

**F8 — the bearer token comparison is not constant-time.** SPEC §4 says "Bearer
token, constant comparison against `VAULT_TOKEN`". The code used `!=` on `str`,
which short-circuits at the first differing byte and leaks the length of the
shared prefix. Fixed with `secrets.compare_digest` — stdlib, no new dependency.

**F9 — `reindex` produced slugs that violate SPEC §2.3.** It used `path.stem`
verbatim. Files on disk are truth and disk names are arbitrary, so a restored
backup or hand-copied artifact called `A Capital File.html` became the slug
`A Capital File` — spaces and capitals in a URL, against §2.3's `[a-z0-9-]`.
Observed on four hostile filenames, all invalid. Now slugified (idempotent, so
normally-published slugs never churn); the real filename is still recorded in
`filename` so `/raw/` serves it.

**F10 — `Path.glob("*.htm*")` is case-sensitive on Linux, so `RESTORED.HTML` was
never indexed at all.** Four files on disk produced three rows. An artifact
sitting on disk that never appears anywhere is an invariant 1 failure, and
restored files are exactly the case invariant 1 exists for. Replaced with a
case-insensitive scan.

**Checked and clean** (no defect, regression tests added anyway since `slugify` is
the only thing standing between `idea:slug` and the filesystem):
- Path traversal via `idea:slug` — `../../etc/passwd` → `etcpasswd`,
  `/absolute/path` → `absolutepath`. Every write resolves inside `content/`.
- Jinja autoescape is **on**, and neither template uses `|safe` or `innerHTML`.
- `/raw/{slug}` builds its path from the DB `filename` column, which only ever
  holds `dest.name` or a globbed `path.name`. No traversal reachable.

<!-- WORKFLOW RESULTS APPENDED BELOW -->
