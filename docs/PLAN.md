# Ideas Vault — Build Plan

Work top to bottom. One task per Claude Code session; `/clear` between tasks so
context stays clean. Each task has an **acceptance command** — run it, paste the real
output, then check the box. Do not check a box on the strength of an assertion.

The repo already contains a working, tested skeleton, so this is a hardening and
deployment plan rather than a from-scratch build. **M1 and M2 alone give you a
usable vault.** Everything after that is compounding value, not prerequisite.

---

## M0 — Orient (20 min, no code)

- [x] **0.1** Read `CLAUDE.md`, `docs/PRD.md`, `docs/SPEC.md`

> Read CLAUDE.md, docs/PRD.md and docs/SPEC.md, then walk the code in app/.
> Give me a file-by-file summary of what exists, and list any place where the
> implementation contradicts the spec. Do not change anything yet.

**Accept:** a summary naming all five modules, plus either a list of discrepancies or
an explicit statement that there are none.

**Done.** All five modules present and matching the spec's shape: `metadata.py`
(parse + fallback chains, never raises), `db.py` (schema, upsert, visibility-filtered
list, get, delete), `ingest.py` (single `publish()` path, `drain_inbox`, `reindex`),
`main.py` (8 routes, token dependency, inbox poller, boot auto-reindex), and the
templates/static layer (`index.html`, `detail.html`, `style.css`).

Six discrepancies found. Numbering kept for reference in later tasks:

1. **`reindex` inflates `revision`.** It calls `db.upsert`, which always takes the
   UPDATE branch and does `revision=revision+1`. A no-op reindex moved an idea 2 → 3.
   **Resolved by decision:** `revision` counts content changes, not writes. SPEC §2.2
   now carries the exemption; `reindex` and identical-sha republish must preserve it.
   Fix in 1.2.
2. **Byte-identical republish bumps `revision`,** contradicting SPEC §2.4's "no-op
   update either way". `publish` computes the sha but only uses it for the collision
   guard, never to short-circuit. Same decision as #1. Fix in 1.2.
3. **~~SPEC §7 test 14 is unsatisfiable~~ — withdrawn.** A prior session claimed no
   file can fail the inbox path. Not so: an *empty* file fails closed and is left in
   place, while good and malformed files both publish and archive. Test 14 passes as
   written. SPEC §6 and §7.14 reworded to say "empty or oversized" rather than
   "unparseable", since malformed HTML publishing is invariant 4 working correctly.
4. **Slug collision guard is narrower than SPEC §2.4.** `ingest.py` ANDs an on-disk
   sha check onto the spec's condition, so a stale or rebuilt index can let
   `dest.write_bytes` overwrite a different artifact — the one loss invariant 1
   exists to prevent. Fix in 1.2.
5. **`tunnel` will crash-loop at 2.1.** No `profiles:` key and no `:?` guard on
   `CF_TUNNEL_TOKEN`, so it starts three milestones before M3 creates the tunnel.
   Fix in 2.0.
6. **`POST /api/reindex` 500s when `vault.db` has been deleted** —
   `sqlite3.OperationalError: no such table: ideas`. `db.init()` runs only in the boot
   lifespan, so reindex alone cannot rebuild a missing index. **SPEC §7 test 11 fails
   as written**, and this is invariant 1's headline promise. Missed previously because
   the check deleted the DB and rebooted, which does call `init()`. Fix in 1.2.

Smaller notes: all routes are GET-only, so `HEAD /raw/…` returns 405 — configure the
6.3 monitor for GET. `detail.html` omits Inter from its font link while `style.css`
asks for it, so the detail page silently falls back to `system-ui`; fix in 2.0.
`.env.example` ships `VAULT_TOKEN=change-me-long-random-string`, a known value that
would leave writes open if copied unchanged — prefer an empty value so SPEC §4's
fail-closed 503 triggers instead; fix in 2.0.

---

## M1 — Test suite (1 session)

The skeleton was smoke-tested, not covered. Do this before anything else so every
later change is verifiable.

- [x] **1.1** Write `tests/` against §7 of the spec

> Write a pytest suite covering all 14 requirements in section 7 of docs/SPEC.md.
> Use fastapi.testclient.TestClient and monkeypatch/tmp_path so tests never touch
> /data and never depend on each other's ordering. Add pytest to requirements.txt.
> Do not modify app/ code to make tests pass — if a test reveals a real bug, tell me
> about it separately before fixing.

**Accept:** `pytest -q` shows 14+ passing, 0 failing. `pytest -q` twice in a row gives
identical results (no ordering dependence).

**Done:** 50 passed, 0 failed; identical across three consecutive runs. 21 unit tests
over `metadata.parse()` plus 29 against the app via `fastapi.testclient`. pytest and
httpx live in a separate `requirements-dev.txt`, so `requirements.txt` is still five
packages and the image ships neither.

- [x] **1.2** Fix whatever 1.1 surfaced

> Here are the failures from 1.1. Fix the application code, not the tests. After each
> fix, re-run pytest and show me the output.

**Accept:** full suite green.

**Done:** ten defects fixed — F1, F2, F4, F6 from 0.1, plus F7 (`reindex` was not
total, so `/raw/`'s "Run POST /api/reindex" advice could never clear a stale row),
F8 (token comparison not constant-time, SPEC §4), F9 (`reindex` produced slugs
violating SPEC §2.3 for arbitrary filenames), F10 (case-sensitive glob made
`RESTORED.HTML` invisible). F3 was withdrawn, not a defect. See
`.claude/notes/orientation.md`.

---

## M2 — Run it locally and file real artifacts (30 min)

- [x] **2.0** Clear the blockers 0.1 found before booting compose

Three small fixes, all outside `app/`:
- `docker-compose.yml`: add `profiles: ["edge"]` to the `tunnel` service and a
  `:?` guard on `CF_TUNNEL_TOKEN`, so 2.1 does not crash-loop it (finding 5).
- `app/templates/detail.html`: add `Inter` to the font link to match `style.css`.
- `.env.example`: blank the `VAULT_TOKEN` placeholder so a copied-but-unedited
  file fails closed with 503 rather than opening writes on a known token.

**Accept:** `docker compose config --profiles` lists `edge`; `docker compose up -d`
starts `vault` only. `grep Inter app/templates/detail.html` matches.

- [ ] **2.1** Boot via compose

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into VAULT_TOKEN
printf 'VAULT_UID=%s\nVAULT_GID=%s\n' "$(id -u)" "$(id -g)" >> .env
docker compose up -d --build
curl -s localhost:8000/healthz
```

**Accept:** `{"ok":true,"count":0}`

`VAULT_TOKEN` ships empty and compose refuses to start until it is set — that is the
fail-closed guard, not a bug. `VAULT_UID`/`VAULT_GID` run the container as you;
without them `./data` and `./inbox` end up root-owned and 4.1 and 6.1 both need sudo.
Also check `docker compose ps` reports the vault **healthy** and `ls -ld data inbox`
shows your own uid. Full walkthrough in the README's Deploy section.

- [ ] **2.2** Publish three real artifacts you actually have — one with a full meta
      block, one with none, one that contains live JavaScript (a chart or dashboard).

**Accept:** all three appear on `/`; the JS one renders and is interactive inside the
iframe on its detail page; tag chips filter correctly; `/` focuses search.

- [ ] **2.3** Time yourself

**Accept:** publish under 30 seconds, retrieval under 10. If either misses, stop and
re-diagnose before building further — the plan's assumptions are wrong.

---

## M3 — Deploy (1 session)

- [ ] **3.1** Cloudflare Tunnel

1. Zero Trust → Networks → Tunnels → create, copy token to `CF_TUNNEL_TOKEN` in `.env`
2. Public hostname `ideas.<domain>` → `http://vault:8000`
3. `docker compose --profile edge up -d` — **the profile is required.** The tunnel
   does not start without it, and plain `docker compose up -d` will not start it on
   any later run either.

**Accept:** `https://ideas.<domain>/healthz` responds from a device on another network.
`nmap` on the host shows no newly opened inbound port.

- [ ] **3.2** Cloudflare Access

Zero Trust → Access → Applications → add the hostname → policy: emails ending in your
domain, or a specific allow-list.

**Accept:** an incognito window is challenged. Your email gets through.

- [ ] **3.3** Confirm the write boundary still holds

**Accept:** `curl -X POST https://ideas.<domain>/api/publish -F file=@x.html` without
a token returns 401, not an Access redirect that silently succeeds.

- [ ] **3.4** Optional: raw origin isolation

Add `raw.ideas.<domain>` to the same tunnel, set `VAULT_RAW_ORIGIN`.

**Accept:** detail page iframes load from the raw hostname; `/` still loads from the
main one.

---

## M4 — Make publishing effortless (30 min)

- [ ] **4.1** Point a sync folder at the inbox

```bash
rmdir ./inbox && ln -s ~/Dropbox/ideas-inbox ./inbox
```

Or bind-mount the sync folder in `docker-compose.yml` instead of `./inbox`.

**Accept:** saving an HTML file to that folder from your phone publishes it within
10 seconds. The original lands in `_ingested/`.

- [ ] **4.2** Shell alias

```bash
alias vault='VAULT_URL=https://ideas.<domain> VAULT_TOKEN=... ~/ideas-vault/scripts/publish.sh'
```

**Accept:** `vault ~/Downloads/thing.html` prints a JSON result with a working URL.

---

## M5 — MCP publishing (1 session)

This is the task that changes how the vault feels — publishing stops being a separate
step from creating.

- [ ] **5.1** Harden and run the MCP server

> mcp/server.py is a draft. Add: input validation (visibility enum, tag count and
> length, date format), a meta-block injector that replaces an existing idea:* block
> rather than duplicating it when one is already present, httpx timeouts and one
> retry, and clear error messages surfaced back to the tool caller. Then write tests
> for the injector against these three inputs: HTML with no head, HTML with a head,
> HTML that already has an idea:* meta block.

**Accept:** `pytest -q tests/test_mcp.py` green. Publishing a document that already
carries a meta block produces exactly one block, not two.

- [ ] **5.2** Connect it as a custom connector in Claude and publish from a chat

**Accept:** a chat-generated artifact lands in the vault with correct title, tags and
description, and the returned URL opens.

- [ ] **5.3** Write the companion skill

> Write a skill at ~/.claude/skills/vault-publish/SKILL.md that triggers when I've
> produced a shareable HTML artifact. It should emit the idea:* meta block into the
> artifact's head as a matter of course, then offer to publish via the vault MCP
> tool. It must call list_ideas first to check whether a related idea already exists
> and, if so, suggest reusing that slug so the idea updates instead of duplicating.

**Accept:** in a fresh chat, generating an artifact prompts an offer to publish, and
publishing a revision of something already filed reuses the original slug.

---

## M6 — Make it survivable (1 session)

- [ ] **6.1** Backups

> Add scripts/backup.sh that tars ./data to a timestamped file, keeps the last 14,
> and optionally syncs to Cloudflare R2 with rclone if RCLONE_REMOTE is set. Add a
> restore.sh that takes an archive and restores it. Document both in the README.

**Accept:** run `backup.sh`, delete `./data` entirely, run `restore.sh`, then
`POST /api/reindex` — and every idea is back. **Actually do this test.** An untested
backup is not a backup.

- [ ] **6.2** Logging and health

> Replace the print() calls with structured JSON logging via the stdlib logging
> module — one line per publish with slug, action, bytes, duration_ms. Add a
> uvicorn access log format. Do not add a dependency.

**Accept:** `docker compose logs vault` shows parseable JSON on publish.

- [ ] **6.3** Health alert

Cloudflare Zero Trust health check, or an external monitor, on `/healthz`.

**Accept:** stopping the container produces an alert within 5 minutes.

---

## Deferred — build only when a trigger fires

| Item | Trigger | Notes |
|---|---|---|
| SQLite FTS5 + server-side filtering | > 800 artifacts, or index feels slow | Schema already supports it |
| Public tier | You actually want to publish externally | Second container, `VAULT_VIEWER_LEVEL=public`, same volume |
| Revision history | You want to read a superseded version | Keep `content/<slug>/v<n>.html`; breaks invariant 1, needs care |
| Auto-tagging | > 50 legacy artifacts with no tags | One LLM call at ingest, closed tag vocabulary |
| OpenAPI 3.1 + generated SDK | You want consistency with LinkFlow conventions | Cheap: eight endpoints |

Resist all five until the trigger fires. The vault's value is that it is small.

---

## Session hygiene for Claude Code

- `/clear` between tasks. These tasks are independent; carried context causes drift.
- `/plan` before M1 and M5 — both have enough shape to be worth reviewing before edits.
- After each task: `pytest -q`, then commit with the task ID in the message
  (`M1.1: test suite covering spec §7`).
- If Claude proposes a new dependency, an ORM, a build step, or a login page, that
  contradicts `CLAUDE.md`. Say no and point at the invariants.
- The two easiest invariants to break accidentally are **#1** (putting
  non-recoverable data in SQLite) and **#5** (rendering artifact HTML inline instead
  of in the iframe). Watch for both in any diff touching `db.py` or the templates.
