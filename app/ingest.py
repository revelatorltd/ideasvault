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

    # Collision guard: same title, different content, no explicit slug -> suffix it.
    if not meta.slug_was_explicit:
        existing = db.get(meta.slug)
        sha = hashlib.sha256(html_bytes).hexdigest()
        if existing and existing["sha256"] != sha:
            target = CONTENT_DIR / f"{meta.slug}.html"
            if target.exists() and _sha_of(target) != sha:
                meta.slug = f"{meta.slug}-{sha[:6]}"

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    dest = CONTENT_DIR / f"{meta.slug}.html"
    dest.write_bytes(html_bytes)

    action = db.upsert(
        meta,
        filename=dest.name,
        size=len(html_bytes),
        sha=hashlib.sha256(html_bytes).hexdigest(),
    )
    return {"action": action, "slug": meta.slug, "title": meta.title,
            "tags": meta.tags, "date": meta.date, "url": f"/i/{meta.slug}"}


def _sha_of(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
