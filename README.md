# Ideas Vault

A self-hosted repository for self-contained HTML artifacts. Drop a file in a folder,
it appears on the index as a card with a title, tags, description and date. Click the
card, read the artifact. No URLs to manage, no rebuild step, no CMS.

## Setup (about 10 minutes)

```bash
cp .env.example .env          # set VAULT_TOKEN to a long random string
docker compose up -d --build  # vault on 127.0.0.1:8000
```

To put it on a real hostname with no open ports and no certificate management:

1. Cloudflare Zero Trust → Networks → Tunnels → create a tunnel, copy the token
   into `CF_TUNNEL_TOKEN` in `.env`.
2. Add a public hostname: `ideas.yourdomain.com` → `http://vault:8000`.
3. Zero Trust → Access → Applications → add `ideas.yourdomain.com`, policy
   "emails ending in @yourcompany.com". Now only your team can read it.

Publishing then works three ways:

| Way | How | Best for |
|---|---|---|
| Inbox folder | Drop `.html` into `./inbox/` | Downloading an artifact and forgetting about it |
| API | `VAULT_URL=… VAULT_TOKEN=… ./scripts/publish.sh file.html` | Scripts and CI |
| MCP tool | `publish_idea` from a Claude chat | Publishing straight out of the conversation that produced it |

Point a sync folder (Dropbox, Drive, iCloud) at `./inbox/` and publishing from a
phone becomes "save file to folder".

## Metadata contract

All metadata lives inside the artifact, so the file is the only thing you manage.
Add this to `<head>`:

```html
<meta name="idea:title"       content="Revelator Intelligence Layer">
<meta name="idea:slug"        content="revelator-intelligence-layer">
<meta name="idea:tags"        content="architecture, world-models, ops">
<meta name="idea:description" content="Four-layer design replacing middle management.">
<meta name="idea:date"        content="2026-08-25">
<meta name="idea:visibility"  content="private">
```

Every field falls back, so a file with none of it still publishes:

| Field | Fallback |
|---|---|
| title | `<title>`, then first `<h1>`, then the filename |
| slug | slugified title; on a title collision with different content, a 6-char hash is appended |
| description | `<meta name="description">`, then the first paragraph over 40 characters |
| tags | `<meta name="keywords">`, else none |
| date | today |
| visibility | `private` |

**Slug is the update key.** Republishing with the same slug replaces that idea in
place and bumps its revision counter. That is how you iterate on an idea without
accumulating `-v2`, `-final`, `-final-2`.

## How it serves artifacts

The detail page is thin chrome — back link, title, tags, date — over an iframe. The
artifact is served from `/raw/<slug>` with `Content-Security-Policy: sandbox
allow-scripts`, which gives it a unique origin. Its scripts run (so charts and
dashboards work) but cannot read the vault's cookies or storage. For strict
isolation, set `VAULT_RAW_ORIGIN` to a second hostname pointed at the same
container and serve raw content from there.

## Operating notes

- **State**: `./data/content/*.html` is the source of truth. `vault.db` is a
  disposable index — `POST /api/reindex` rebuilds it from disk. Back up `./data/`.
- **Scale**: search and tag filtering are client-side, which is fine to roughly
  1,000 artifacts. Past that, move filtering server-side with SQLite FTS5.
- **Visibility**: `VAULT_VIEWER_LEVEL` sets the ceiling for what a reader sees.
  Run one container at `private` behind Cloudflare Access for yourself, and if you
  ever want a public face, run a second container at `public` on the same volume.
- **Deletes**: `DELETE /api/ideas/<slug>` removes the row and the file. There is no
  undo, so rely on the `./data/` backup.

## Layout

```
app/metadata.py   metadata contract + fallbacks
app/ingest.py     one publish path for upload, inbox, and reindex
app/db.py         SQLite index
app/main.py       routes + inbox watcher
app/templates/    index (cards, search, tag chips), detail (chrome + iframe)
mcp/server.py     publish_idea / list_ideas / get_idea_url
scripts/publish.sh
```

## Keyboard

`/` focuses search, `Esc` clears it. Tag chips toggle.
