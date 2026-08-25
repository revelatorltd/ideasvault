# Ideas Vault

A self-hosted repository for self-contained HTML artifacts. Drop a file in a folder,
it appears on the index as a card with a title, tags, description and date. Click the
card, read the artifact. No URLs to manage, no rebuild step, no CMS.

## Deploy

Three stages. Each one ends in a check you can actually run, so a failure is
localised rather than discovered three steps later.

### 1. Local, no ingress (about 5 minutes)

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into VAULT_TOKEN
printf 'VAULT_UID=%s\nVAULT_GID=%s\n' "$(id -u)" "$(id -g)" >> .env
docker compose up -d --build
curl -s localhost:8000/healthz
```

Expect `{"ok":true,"count":0}`.

`VAULT_TOKEN` ships **empty on purpose** and compose refuses to start until you set
it — writes fail closed rather than defaulting open, so there is no "forgot to set
it" state where the vault is publicly writable. If you skip the paste you get
`required variable VAULT_TOKEN is missing a value`, which is the guard working.

`VAULT_UID`/`VAULT_GID` make the container run as you. Without them everything the
vault writes is owned by `root`, and you need `sudo` to drop a file in your own
inbox, to point a sync folder at it, or to back `./data` up. They default to 1000,
which is right on most single-user machines; the `id -u` line above is exact.

Then confirm the pieces that matter:

```bash
docker compose ps                       # vault only, and healthy
echo '<title>Hello</title><p>A first artifact, long enough for a description.</p>' > inbox/hello.html
sleep 5 && curl -s localhost:8000/api/ideas   # the artifact appears
ls -ld data inbox                       # owned by you, not root
```

Inbox pickup takes two polls (about 4s) — a file is held until its size and mtime
stop changing, so a half-written sync download is never published as truth.

### 2. Public hostname, still no open ports

1. Cloudflare Zero Trust → Networks → Tunnels → create a tunnel, copy the token
   into `CF_TUNNEL_TOKEN` in `.env`.
2. Add a public hostname: `ideas.yourdomain.com` → `http://vault:8000`.
3. Start the edge. **The tunnel is behind a compose profile and will not start
   without it** — that is deliberate, since it crash-loops when no tunnel exists
   yet:

```bash
docker compose --profile edge up -d
```

Plain `docker compose up -d` from then on will *not* start the tunnel. The profile
has to be named every time.

Check from a device on another network: `https://ideas.yourdomain.com/healthz`
responds, and `nmap` against the host shows no newly opened inbound port.

### 3. Reader auth at the edge

Zero Trust → Access → Applications → add `ideas.yourdomain.com`, policy "emails
ending in @yourcompany.com". An incognito window should now be challenged, and your
own email should get through.

Then verify the write boundary separately, because Access protects *reads* and the
bearer token protects *writes* — they are different mechanisms and only one of them
lives in this codebase:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://ideas.yourdomain.com/api/publish -F file=@x.html
```

Expect `401`. Anything else — especially a 200, or an Access redirect that silently
succeeds — means writes are not actually protected. Stop and fix that before
publishing anything real.

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
| slug | slugified title; on a collision with different content already on disk, a hash suffix is appended (6 chars, widening if that is taken too) |
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
allow-scripts allow-popups allow-forms`, which gives it a unique origin. Its scripts run (so charts and
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
