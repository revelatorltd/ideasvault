"""Test fixtures.

Two things make this app awkward to test, and both are handled here rather than
in every test:

1. Config is read into module globals at import time, so monkeypatching
   os.environ has no effect. Patch the globals instead.
2. The app's lifespan starts a background inbox poller. Entering TestClient as
   a context manager would start it, and it would race the inbox test. So the
   client is built without `with`, and this fixture does the one useful thing
   boot does: db.init().
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app import db, ingest, main

TOKEN = "test-token"


@dataclass
class Vault:
    client: TestClient
    content: pathlib.Path
    inbox: pathlib.Path
    db_path: pathlib.Path
    token: str = TOKEN

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def publish(
        self,
        html: str | bytes,
        filename: str = "artifact.html",
        token: str | None = TOKEN,
    ):
        body = html.encode() if isinstance(html, str) else html
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.post(
            "/api/publish",
            files={"file": (filename, body, "text/html")},
            headers=headers,
        )

    def drain(self) -> list[dict]:
        """Run the inbox to completion, which takes two polls.

        drain_inbox holds a file until its size and mtime are stable across
        consecutive scans, so a partially-written file is never published. The
        first call registers what it saw; the second acts on it.
        """
        ingest.drain_inbox()
        return ingest.drain_inbox()

    def rows(self) -> list[dict]:
        with db.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM ideas ORDER BY slug")]

    def revision(self, slug: str) -> int:
        return db.get(slug)["revision"]

    def files(self) -> list[str]:
        return sorted(p.name for p in self.content.glob("*.html"))


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Vault:
    content, inbox = tmp_path / "content", tmp_path / "inbox"
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "vault.db"))
    monkeypatch.setattr(ingest, "CONTENT_DIR", content)
    monkeypatch.setattr(ingest, "INBOX_DIR", inbox)
    monkeypatch.setattr(ingest, "ARCHIVE_DIR", inbox / "_ingested")
    monkeypatch.setattr(main, "PUBLISH_TOKEN", TOKEN)
    monkeypatch.setattr(main, "VIEWER_LEVEL", "private")
    content.mkdir(parents=True)
    inbox.mkdir(parents=True)
    ingest._FAILED.clear()  # module state; would leak between tests
    ingest._PENDING.clear()
    db.init()
    return Vault(TestClient(main.app), content, inbox, tmp_path / "vault.db")


@pytest.fixture
def vault_html():
    """Build an artifact. Every part is optional so fallback chains can be probed."""

    def build(
        title: str | None = "Test Idea",
        h1: str | None = None,
        meta: dict[str, str] | None = None,
        body: str = "Some body text.",
        head: bool = True,
    ) -> str:
        tags = "".join(
            f'<meta name="{k}" content="{v}">' for k, v in (meta or {}).items()
        )
        title_tag = f"<title>{title}</title>" if title else ""
        h1_tag = f"<h1>{h1}</h1>" if h1 else ""
        inner = f"{h1_tag}<p>{body}</p>"
        if not head:
            return f"<html><body>{inner}</body></html>"
        return (
            f"<!DOCTYPE html><html><head><meta charset='utf-8'>{title_tag}{tags}"
            f"</head><body>{inner}</body></html>"
        )

    return build
