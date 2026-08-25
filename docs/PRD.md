# Ideas Vault — PRD

**Status:** approved for build · **Owner:** Bruno · **Version:** 1.0

---

## 1. Problem

HTML artifacts get generated constantly — architecture diagrams, dashboards,
strategy docs, specs — and then land in `~/Downloads` and die there. Nothing
accumulates. There is no way to answer "what did I conclude about this in April?"
without hunting through chat history.

Existing options all fail on the same axis, which is friction at the moment of
publishing:

| Option | Why it fails |
|---|---|
| Static site generator | Requires frontmatter, a build step, and a git commit per idea |
| Notion / Confluence | Mangles self-contained HTML; embedded JS does not run |
| Cloud storage link | No index, no tags, links rot, no browsing |
| Blog platform | Wrong shape; assumes an audience and a publishing ritual |

The requirement is not "a place to put files." It is **publishing that costs zero
decisions.** Any step that asks the author to name a URL, pick a folder, or fill in a
form is a step where filing stops happening.

## 2. Users

| User | Volume | Needs |
|---|---|---|
| Author (primary) | Daily | File in seconds; find anything later; update without renaming |
| Colleague / board member | Occasional | Open a shared link and read it, on any device |
| An LLM agent | Per conversation | Publish an artifact and search prior thinking via MCP |

The third user is the one that compounds. Once a chat can query what has already
been concluded, the vault stops being an archive and becomes working memory.

## 3. Jobs to be done

1. When I finish an artifact, I want to file it without leaving what I was doing, so
   it doesn't sit in Downloads.
2. When I half-remember an idea, I want to find it by tag or fragment of title in
   seconds, so I don't rewrite work I already did.
3. When I share an idea, I want one link that keeps working, so I'm not re-sending files.
4. When I revise an idea, I want it to replace the old one, so I don't accumulate
   `-v2-final-actually-final`.
5. When I'm publishing from my phone, I want it to work the same way, so filing isn't
   desk-bound.

## 4. Success metrics

| Metric | Target | How measured |
|---|---|---|
| Time to publish | < 30 seconds, zero decisions | Timed manually at M2 |
| Filing rate | 100% of new artifacts | Count in vault vs. count generated, weekly |
| Time to retrieve | < 10 seconds | Timed manually at M2 |
| Duplicate ideas from revision | 0 | `SELECT title, COUNT(*) … HAVING COUNT(*) > 1` |
| Index p95 latency | < 100 ms | Access logs |
| Ops burden | 0 minutes/week | Honest self-report at 30 days |

The one to watch is **filing rate**. If it isn't near 100% after two weeks, the
friction is somewhere other than where we assumed, and the next milestone should
change accordingly.

## 5. Scope (v1)

- Three publish paths: inbox folder, authenticated API, MCP tool
- Metadata read from the artifact's own `<meta>` tags, with a fallback for every field
- Card index: title, description, tags, date, revision badge
- Client-side live search and tag filtering, `/` to focus search
- Detail view: thin chrome over a sandboxed iframe
- Three visibility levels: `private`, `internal`, `public`
- Reader auth at the edge via Cloudflare Access; bearer token for writes
- Index rebuildable from disk

## 6. Non-goals

Explicitly out, and each has a reason:

| Non-goal | Reason |
|---|---|
| Browser-based editing | Artifacts are generated elsewhere; an editor invites drift |
| Comments / reactions | No audience loop to serve |
| Multi-user auth in-app | Cloudflare Access does it better, for free, at the edge |
| Full-text search of bodies | Title + description + tags covers retrieval at this volume |
| Themes, i18n, customization | One user, one language, one aesthetic |
| Merging with LinkFlow | Would drag a 30-minute setup onto a platform stack |

## 7. Assumptions

Labelled because they should be checked, not trusted:

- **A1** Artifact volume stays under ~1,000 for at least a year. Client-side filtering
  is fine to that point; past it, move to SQLite FTS5.
- **A2** Artifacts are self-contained — inline CSS/JS, no local asset dependencies.
  Files pulling from a relative `./assets/` path will break.
- **A3** Single author. Concurrent publishes are not a real scenario; last-write-wins
  on a slug is acceptable.
- **A4** A Cloudflare-managed domain and a Docker host are available.
- **A5** Artifacts are under 15 MB. Larger ones are rejected with a clear error.

## 8. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Volume loss destroys everything | High | `./data/` backup is the whole DR plan; verify a restore at M6 |
| Tag sprawl makes filters useless | Medium | Closed vocabulary; audit at 20 tags |
| Scope creep toward a CMS | Medium | Non-goals table is load-bearing; CLAUDE.md repeats it |
| Artifact JS reads vault session | High | Unique-origin sandbox; optional separate raw hostname |
| Filing still doesn't happen | Medium | Measure at 2 weeks; if low, the friction is elsewhere — re-diagnose |
