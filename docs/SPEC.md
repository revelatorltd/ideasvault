# Ideas Vault — Technical Specification

**Version:** 1.0 · Companion to `docs/PRD.md` · Build order in `docs/PLAN.md`

---

## 1. Stack

| Layer | Choice | Why not something else |
|---|---|---|
| Runtime | Python 3.12 | Matches the rest of the toolchain |
| Web | FastAPI + Jinja2 | Async, typed, templates without a second service |
| Store | Files on disk + SQLite | The index is disposable; Postgres buys nothing at one user |
| Parsing | BeautifulSoup4 | Tolerant of malformed HTML, which artifacts often are |
| Container | Docker Compose | Kubernetes is overhead for a single stateless container |
| Edge | Cloudflare Tunnel + Access | No open ports, no certificates, auth without app code |

Five runtime dependencies. Adding a sixth requires a stated reason.

## 2. Data model

### 2.1 Storage layout

```
/data
  vault.db            # SQLite index — disposable, rebuildable
  content/<slug>.html # artifacts — SOURCE OF TRUTH, back this up
  inbox/              # drop zone, watched
  inbox/_ingested/    # originals moved here after successful publish
```

### 2.2 Schema

```sql
CREATE TABLE ideas (
    slug        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags_json   TEXT NOT NULL DEFAULT '[]',
    date        TEXT NOT NULL,              -- ISO-8601 date, authored not ingested
    visibility  TEXT NOT NULL DEFAULT 'private',
    filename    TEXT NOT NULL,
    bytes       INTEGER NOT NULL DEFAULT 0,
    sha256      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    revision    INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ideas_date ON ideas(date DESC);
```

Every column is derivable from the artifact file plus filesystem metadata. That is the
constraint that keeps `reindex` total.

### 2.3 Metadata contract

```html
<meta name="idea:title"       content="Revelator Intelligence Layer">
<meta name="idea:slug"        content="revelator-intelligence-layer">
<meta name="idea:tags"        content="architecture, world-models, ops">
<meta name="idea:description" content="Four-layer design replacing middle management.">
<meta name="idea:date"        content="2026-08-25">
<meta name="idea:visibility"  content="private">
```

Fallback chains — parsing must never raise:

| Field | Chain | Constraints |
|---|---|---|
| title | `idea:title` → `<title>` → first `<h1>` → filename → "Untitled idea" | ≤ 200 chars |
| slug | `idea:slug` → slugify(title) → `idea-<sha1[:8]>` | ≤ 72 chars, `[a-z0-9-]` |
| description | `idea:description` → `description` → first `<p>`/`<h2>`/`<li>` over 40 chars → "" | ≤ 400 chars |
| tags | `idea:tags` → `keywords` → `[]` | ≤ 8, lowercased, split on `,` or `;` |
| date | `idea:date` if `YYYY-MM-DD` → today | strict format check |
| visibility | `idea:visibility` if in enum → `private` | `private\|internal\|public` |

### 2.4 Slug resolution

The one piece of real logic in the system.

```
if idea:slug present:
    use it verbatim (slugified). Same slug ⇒ replace in place, revision += 1.
else:
    candidate = slugify(title)
    if candidate exists AND its sha256 differs from this upload:
        candidate = f"{candidate}-{sha256[:6]}"     # distinct idea, same title
    use candidate
```

Consequence worth stating plainly: **an explicit slug means "this is the same idea,
updated." No slug plus a changed body means "this is a new idea."** Republishing
byte-identical content is a no-op update either way.

## 3. HTTP interface

| Method | Path | Auth | Returns |
|---|---|---|---|
| GET | `/` | edge | Card index (HTML) |
| GET | `/i/{slug}` | edge | Detail chrome + iframe (HTML) |
| GET | `/raw/{slug}` | edge | Artifact, sandboxed |
| GET | `/api/ideas` | edge | `{ideas: [...]}` |
| GET | `/healthz` | none | `{ok, count}` |
| POST | `/api/publish` | bearer | `{action, slug, title, tags, date, url}` |
| POST | `/api/reindex` | bearer | `{indexed: n}` |
| DELETE | `/api/ideas/{slug}` | bearer | `{deleted: slug}` |

Status codes: `201` created, `200` updated, `400` malformed or oversized, `401` bad
token, `404` unknown slug or visibility-filtered, `410` indexed but file missing,
`503` `VAULT_TOKEN` unset.

Errors return `{"detail": "..."}` written for a human: what happened, what to do.

### 3.1 Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VAULT_TOKEN` | *(unset)* | Bearer token for writes; unset disables all writing |
| `VAULT_DB` | `/data/vault.db` | Index location |
| `VAULT_CONTENT` | `/data/content` | Artifact store |
| `VAULT_INBOX` | `/data/inbox` | Watched drop folder |
| `VAULT_VIEWER_LEVEL` | `private` | Visibility ceiling for readers |
| `VAULT_RAW_ORIGIN` | `""` | Separate hostname for raw artifacts |
| `VAULT_POLL_SECONDS` | `3` | Inbox scan interval |
| `VAULT_MAX_BYTES` | `15728640` | Upload limit |

## 4. Security model

Three boundaries, each doing one job.

**Reader auth — edge.** Cloudflare Access in front of the hostname. The application
has no login, no sessions, no password storage. Compromise of the container does not
leak credentials because there are none.

**Writer auth — application.** Bearer token, constant comparison against
`VAULT_TOKEN`. If unset, writes return `503` rather than defaulting open.

**Artifact isolation — browser.** This is the interesting one. Artifacts contain
author-controlled JavaScript that must run for dashboards to work. `/raw/{slug}`
sends `Content-Security-Policy: sandbox allow-scripts allow-popups allow-forms` —
omitting `allow-same-origin` puts the document in a unique opaque origin, so its
scripts execute but cannot read vault cookies, `localStorage`, or the parent frame.
The detail page's iframe carries the matching `sandbox` attribute as defence in depth.

Setting `VAULT_RAW_ORIGIN` to a second hostname adds origin separation on top, for
when an artifact is genuinely untrusted.

**Never** inline artifact HTML into a Jinja template. The iframe is the boundary.

### 4.1 Privacy and GDPR

Artifacts are first-party content authored by the operator, so most GDPR surface does
not apply. What does:

- Cloudflare Access logs reader email addresses. That is a processing activity; note
  it if the vault is shared beyond the author, and set log retention deliberately.
- If an artifact contains third-party personal data (a client list, an org chart),
  `DELETE /api/ideas/{slug}` plus a backup rotation is the erasure path. Backups are
  where deletion requests actually go to die — set retention to a bounded window.
- No analytics, no third-party scripts in vault chrome. Google Fonts is the only
  external request; self-host the two families if even that is unwanted.

## 5. Performance

Targets at ~1,000 artifacts on modest hardware:

| Operation | Target |
|---|---|
| `GET /` | < 100 ms p95 |
| `GET /i/{slug}` | < 50 ms p95 |
| `GET /raw/{slug}` | disk-bound |
| `POST /api/publish` | < 500 ms p95 |
| Inbox pickup | < 5 s from file appearing |
| Full reindex, 1,000 files | < 30 s |

Search and tag filtering run client-side over rendered DOM. At 1,000 cards the index
payload is roughly 300 KB — acceptable. Past that, the migration is SQLite FTS5 with
server-side filtering and pagination; the schema already supports it.

## 6. Failure modes

| Failure | Behaviour | Recovery |
|---|---|---|
| Malformed HTML | Publishes with fallback metadata | None needed |
| Row exists, file missing | `410` with an instruction | `POST /api/reindex` |
| Index corrupt or deleted | Empty index at boot triggers auto-reindex | Automatic |
| Inbox file unparseable | Stays in `inbox/`, logged as `failed` | Inspect and fix |
| Oversized upload | `400` with the actual size and the limit | Split or raise limit |
| Duplicate title, different content | Second gets `-<hash6>` suffix | None needed |
| Volume lost | Total loss | Restore `./data/` — the only DR path |

## 7. Testing requirements

`pytest -q` must cover, at minimum:

1. Metadata: full meta block parsed correctly
2. Metadata: every fallback in the chain, including a file with no `<head>`
3. Metadata: malformed HTML does not raise
4. Slug: explicit slug republish updates in place, `revision` becomes 2
5. Slug: same title, different content, no explicit slug ⇒ suffixed slug
6. Slug: byte-identical republish stays at one row
7. Auth: every write endpoint returns 401 without a token
8. Auth: writes return 503 when `VAULT_TOKEN` is unset
9. Security: `/raw/{slug}` carries the CSP sandbox header
10. Security: detail page iframe has the `sandbox` attribute
11. Reindex: deleting `vault.db` and reindexing restores every row
12. Visibility: `VAULT_VIEWER_LEVEL=public` hides private ideas from index, detail, and raw
13. Limits: oversized upload rejected with 400
14. Inbox: `drain_inbox` publishes and archives; a bad file is left in place
