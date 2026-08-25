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
    db.init()
    return Vault(TestClient(main.app), content, inbox, tmp_path / "vault.db")
