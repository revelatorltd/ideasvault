# Ideas Vault — working notes for Claude Code

Read `docs/PRD.md` for why this exists, `docs/SPEC.md` for how it behaves, and
`docs/PLAN.md` for what to build next. Work one task at a time from PLAN.md.

## What this is

A self-hosted repository for self-contained HTML artifacts. Publishing is "put the
file in a folder." Metadata lives inside the HTML in `<meta name="idea:*">` tags, so
the file is the only thing anyone manages.

Single user. No billing, no sessions, no multi-tenancy. Reader authentication is
handled at the edge by Cloudflare Access, not in this codebase.

## Commands

```bash
pip install -r requirements.txt --break-system-packages   # local deps
pytest -q                                                 # full test suite
uvicorn app.main:app --reload --port 8000                 # local dev server
docker compose up -d --build                              # run as deployed
curl -s localhost:8000/healthz                            # liveness + count
```

Local dev needs these set or it will try to write to `/data`:

```bash
export VAULT_DB=./dev/vault.db VAULT_CONTENT=./dev/content \
       VAULT_INBOX=./dev/inbox VAULT_TOKEN=devtoken
```

## Architecture invariants

Do not break these without saying so explicitly and explaining why.

1. **Files on disk are truth. SQLite is a disposable cache.** `POST /api/reindex`
   must always be able to rebuild the entire index from `content/*.html`. Never put
   data in the database that cannot be recovered from the artifact files.
2. **One ingest path.** Uploads, inbox drops, and reindex all go through
   `ingest.publish()`. Never add a second write path.
3. **Slug is the update key.** Republishing the same slug replaces in place and
   bumps `revision`. It must never create a duplicate row or a second file.
4. **Metadata parsing never raises.** Every field has a fallback chain. A garbage
   file still publishes with sensible defaults; it does not 500.
5. **Artifacts are hostile input.** They contain author-controlled JavaScript.
   `/raw/{slug}` must keep its `Content-Security-Policy: sandbox` header and the
   detail page must keep the iframe `sandbox` attribute. Never inline artifact HTML
   into a vault template.
6. **Writes need the bearer token.** Reads are protected at the edge; writes are
   protected in code. Never add an unauthenticated write endpoint.

## Conventions

- Python 3.12, FastAPI, Jinja2, stdlib `sqlite3`. No ORM, no Alembic, no Redis.
- Type hints on function signatures. `from __future__ import annotations` at top.
- No new dependencies without asking first. The dependency list is deliberately five
  packages long.
- Interface copy: sentence case, active voice, plain verbs. Errors say what happened
  and what to do — "The index has this idea but its file is missing. Run
  POST /api/reindex." Not "Error: file not found."
- CSS lives in `app/static/style.css` and uses the existing custom properties. Do not
  add a build step, a framework, or a CSS preprocessor.

## Definition of done

A task is done when `pytest -q` passes, the acceptance command in PLAN.md produces
the stated output, and PLAN.md is updated to check the task off. Run the acceptance
command and paste real output — do not assert that something works without showing it.

## Out of scope

Browser-based editing. Comments. Multi-user auth. Full-text search inside artifact
bodies. Anything that looks like a CMS. If a task seems to require one of these, stop
and flag it rather than building it.
