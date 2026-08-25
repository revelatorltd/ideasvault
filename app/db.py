"""SQLite index. Content lives on disk; this table is a rebuildable index."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("VAULT_DB", "/data/vault.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ideas (
    slug          TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    tags_json     TEXT NOT NULL DEFAULT '[]',
    date          TEXT NOT NULL,
    visibility    TEXT NOT NULL DEFAULT 'private',
    filename      TEXT NOT NULL,
    bytes         INTEGER NOT NULL DEFAULT 0,
    sha256        TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    revision      INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ideas_date ON ideas(date DESC);
"""

# Executed on every connection, not just at boot. The index is disposable by
# design, so vault.db may be deleted while the process is running -- if the
# schema were only created in init() every later query would raise "no such
# table: ideas" until a restart. Both statements are IF NOT EXISTS, so this is a
# cheap no-op once the table is there.
_ENSURE = [s.strip() for s in SCHEMA.strip().split(";") if s.strip()]


@contextmanager
def conn():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        for statement in _ENSURE:
            c.execute(statement)
        yield c
        c.commit()
    finally:
        c.close()


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


def upsert(meta, filename: str, size: int, sha: str) -> str:
    """Insert or update by slug. Returns 'created' or 'updated'."""
    with conn() as c:
        existing = c.execute(
            "SELECT sha256, revision FROM ideas WHERE slug = ?", (meta.slug,)
        ).fetchone()
        if existing:
            # SPEC 2.2/2.4: revision counts CONTENT changes, not writes. The sha
            # covers the whole file, so an unchanged sha means nothing about this
            # artifact differs -- a byte-identical republish and a reindex must
            # both leave revision and updated_at alone. Without this, reindex
            # mutates every row it touches and is not a rebuild at all. The other
            # columns are still written, so a filename that changed extension
            # cannot go stale.
            changed = existing["sha256"] != sha
            touch = (
                ", revision = revision + 1, updated_at = datetime('now')"
                if changed else ""
            )
            c.execute(
                f"""UPDATE ideas SET title=?, description=?, tags_json=?, date=?,
                        visibility=?, filename=?, bytes=?, sha256=?{touch}
                    WHERE slug=?""",
                (meta.title, meta.description, json.dumps(meta.tags), meta.date,
                 meta.visibility, filename, size, sha, meta.slug),
            )
            return "updated"
        c.execute(
            """INSERT INTO ideas
                   (slug, title, description, tags_json, date, visibility,
                    filename, bytes, sha256)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (meta.slug, meta.title, meta.description, json.dumps(meta.tags),
             meta.date, meta.visibility, filename, size, sha),
        )
        return "created"


def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["tags"] = json.loads(d.pop("tags_json"))
    return d


def list_ideas(max_visibility: str = "private") -> list[dict]:
    allowed = {"public": ("public",),
               "internal": ("public", "internal"),
               "private": ("public", "internal", "private")}[max_visibility]
    placeholders = ",".join("?" * len(allowed))
    with conn() as c:
        rows = c.execute(
            f"""SELECT * FROM ideas WHERE visibility IN ({placeholders})
                ORDER BY date DESC, updated_at DESC""",
            allowed,
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get(slug: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM ideas WHERE slug = ?", (slug,)).fetchone()
    return _row_to_dict(row) if row else None


def delete(slug: str) -> bool:
    with conn() as c:
        return c.execute("DELETE FROM ideas WHERE slug = ?", (slug,)).rowcount > 0


def prune(keep: set[str]) -> int:
    """Drop every row not in `keep`. Returns the number removed.

    Files on disk are truth, so a reindex that only inserts is not a rebuild: a
    row whose artifact was deleted outside the app would survive forever, and
    /raw/ would keep answering 410 "Run POST /api/reindex" -- advice that never
    works. Only reindex() calls this, with the slugs it actually found.
    """
    with conn() as c:
        if not keep:
            return c.execute("DELETE FROM ideas").rowcount
        placeholders = ",".join("?" * len(keep))
        return c.execute(
            f"DELETE FROM ideas WHERE slug NOT IN ({placeholders})", tuple(keep)
        ).rowcount
