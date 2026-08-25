"""Ingest pipeline. One code path for uploads, inbox drops, and full reindex."""

from __future__ import annotations

import hashlib
import os
import pathlib
import shutil

from . import db, metadata

CONTENT_DIR = pathlib.Path(os.environ.get("VAULT_CONTENT", "/data/content"))
INBOX_DIR = pathlib.Path(os.environ.get("VAULT_INBOX", "/data/inbox"))
ARCHIVE_DIR = INBOX_DIR / "_ingested"
MAX_BYTES = int(os.environ.get("VAULT_MAX_BYTES", 15 * 1024 * 1024))


def publish(html_bytes: bytes, filename: str = "") -> dict:
    """Publish one artifact. Idempotent per slug: same slug replaces in place."""
    if len(html_bytes) > MAX_BYTES:
        raise ValueError(f"Artifact is {len(html_bytes)} bytes; limit is {MAX_BYTES}.")
    if not html_bytes.strip():
        raise ValueError("Artifact is empty.")

    html = html_bytes.decode("utf-8", errors="replace")
    meta = metadata.parse(html, filename=filename)
    sha = hashlib.sha256(html_bytes).hexdigest()

    # Collision guard: same title, different content, no explicit slug -> suffix it.
    #
    # SPEC 2.4 conditions on "candidate exists". The candidate that matters is the
    # FILE, not the index row: files on disk are truth (invariant 1) and the index
    # is disposable, so a rebuilt or partially-lost index must not license
    # overwriting an artifact that is sitting right there. Keying this on the row
    # is how an artifact gets silently destroyed.
    if not meta.slug_was_explicit:
        meta.slug = _free_slug(meta.slug, sha)

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    dest = CONTENT_DIR / f"{meta.slug}.html"
    dest.write_bytes(html_bytes)

    action = db.upsert(meta, filename=dest.name, size=len(html_bytes), sha=sha)
    return {"action": action, "slug": meta.slug, "title": meta.title,
            "tags": meta.tags, "date": meta.date, "url": f"/i/{meta.slug}"}


def _sha_of(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


SLUG_MAX = 72  # SPEC 2.3


def _free_slug(slug: str, sha: str) -> str:
    """Return a slug whose file either does not exist or already holds this sha.

    Escalates the suffix rather than trusting six hex characters to be unique:
    24 bits collide roughly once in 16 million, and the cost of a collision here
    is a destroyed artifact, which is the one outcome invariant 1 exists to rule
    out. If even the full digest is taken by different bytes, refuse -- a clear
    400 is better than a silent overwrite.
    """
    for width in (0, 6, 12, 64):
        candidate = slug if width == 0 else f"{slug[: SLUG_MAX - width - 1]}-{sha[:width]}"
        target = CONTENT_DIR / f"{candidate}.html"
        if not target.exists() or _sha_of(target) == sha:
            return candidate
    raise ValueError(
        f"Cannot file this artifact: {slug}.html and its hashed variants are all "
        f"taken by different content. Publish it with an explicit "
        f"<meta name=\"idea:slug\"> to say which idea it updates."
    )


def drain_inbox() -> list[dict]:
    """Publish every .html in the inbox, then move originals to _ingested/."""
    results = []
    if not INBOX_DIR.exists():
        return results
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INBOX_DIR.glob("*.htm*")):
        try:
            results.append(publish(path.read_bytes(), filename=path.name))
            shutil.move(str(path), str(ARCHIVE_DIR / path.name))
        except Exception as exc:  # keep the file so the failure is inspectable
            results.append({"action": "failed", "file": path.name, "error": str(exc)})
    return results


def reindex() -> int:
    """Rebuild the index from content/ on disk. The DB is always disposable.

    Total in both directions: every artifact on disk gets a row, and every row
    without an artifact is dropped. Revisions are preserved -- see SPEC 2.2.
    """
    seen: set[str] = set()
    for path in sorted(CONTENT_DIR.glob("*.htm*")):
        raw = path.read_bytes()
        meta = metadata.parse(raw.decode("utf-8", errors="replace"), filename=path.name)
        meta.slug = path.stem  # filename on disk is the source of truth for slug
        db.upsert(meta, filename=path.name, size=len(raw),
                  sha=hashlib.sha256(raw).hexdigest())
        seen.add(meta.slug)
    db.prune(seen)
    return len(seen)
