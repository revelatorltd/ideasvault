"""SPEC section 7, requirements 4-14, plus regression guards for the confirmed
defects F1, F2, F4 and F6 recorded in .claude/notes/orientation.md.

Tests are written against the SPEC, not against current behaviour. The F-marked
tests are expected to fail until their fix unit lands -- that is the point of
writing them first.
"""

from __future__ import annotations

import pathlib

from app import db, ingest, main


def _artifact(title: str, body: str, slug: str | None = None, **meta) -> str:
    tags = "".join(f'<meta name="{k}" content="{v}">' for k, v in meta.items())
    slug_tag = f'<meta name="idea:slug" content="{slug}">' if slug else ""
    return (
        f"<!DOCTYPE html><html><head><title>{title}</title>{slug_tag}{tags}"
        f"</head><body><p>{body}</p></body></html>"
    )


# ---------------------------------------------------------------- 7.4-7.6 slug

def test_7_4_explicit_slug_republish_updates_in_place_and_bumps_revision(vault):
    """SPEC 7.4. An explicit slug means "same idea, updated"."""
    first = vault.publish(_artifact("Alpha", "original body", slug="alpha"))
    assert first.status_code == 201
    assert first.json()["action"] == "created"

    second = vault.publish(_artifact("Alpha", "a genuinely changed body", slug="alpha"))
    assert second.status_code == 200
    assert second.json()["action"] == "updated"

    assert len(vault.rows()) == 1, "invariant 3: never a duplicate row"
    assert vault.files() == ["alpha.html"], "invariant 3: never a second file"
    assert vault.revision("alpha") == 2


def test_7_5_same_title_different_content_gets_a_suffixed_slug(vault):
    """SPEC 7.5. No explicit slug plus a changed body means a NEW idea."""
    a = vault.publish(_artifact("Same Title", "first body"), filename="a.html")
    b = vault.publish(_artifact("Same Title", "second, different body"), filename="b.html")

    slug_a, slug_b = a.json()["slug"], b.json()["slug"]
    assert slug_a == "same-title"
    assert slug_b.startswith("same-title-") and slug_b != slug_a
    assert len(vault.rows()) == 2
    assert len(vault.files()) == 2


def test_7_6_byte_identical_republish_is_a_no_op(vault):
    """SPEC 7.6 and 2.4: "Republishing byte-identical content is a no-op update".

    REGRESSION GUARD F2 -- currently the revision is bumped anyway.
    """
    html = _artifact("Idem", "unchanging body", slug="idem")
    vault.publish(html)
    before = vault.revision("idem")
    vault.publish(html)

    assert len(vault.rows()) == 1
    assert vault.files() == ["idem.html"]
    assert vault.revision("idem") == before, (
        "F2: byte-identical republish must not bump revision (SPEC 2.4)"
    )


def test_F1_reindex_is_idempotent_and_preserves_revision(vault):
    """REGRESSION GUARD F1. An index rebuild that mutates data is not a rebuild.

    SPEC 2.2 exempts `revision` from derivability precisely so reindex can
    preserve it.
    """
    vault.publish(_artifact("Rev", "body one", slug="rev"))
    vault.publish(_artifact("Rev", "body two", slug="rev"))
    assert vault.revision("rev") == 2

    for _ in range(2):
        r = vault.client.post("/api/reindex", headers=vault.auth)
        assert r.status_code == 200

    assert vault.revision("rev") == 2, "F1: reindex must not inflate revision"
    assert len(vault.rows()) == 1


def test_F4_publish_never_overwrites_a_different_artifact_on_disk(vault):
    """REGRESSION GUARD F4 -- the artifact-loss case invariant 1 exists to prevent.

    The collision guard in ingest.py only fires when a ROW exists. If the index
    was rebuilt or the row dropped while the file is still on disk, a same-titled
    artifact with different content overwrites it and the original is gone.
    """
    keep = "original content that must survive"
    first = vault.publish(_artifact("Shared", keep), filename="first.html")
    slug = first.json()["slug"]

    db.delete(slug)  # index lost the row; the file on disk is still truth

    vault.publish(_artifact("Shared", "completely different content"), filename="second.html")

    survivor = (vault.content / f"{slug}.html").read_text()
    assert keep in survivor, (
        "F4: publishing must not overwrite a different artifact already on disk"
    )


# ---------------------------------------------------------------- 7.7-7.8 auth

def test_7_7_every_write_endpoint_401s_without_a_token(vault):
    """SPEC 7.7 / invariant 6."""
    assert vault.client.post("/api/publish").status_code == 401
    assert vault.client.post("/api/reindex").status_code == 401
    assert vault.client.delete("/api/ideas/anything").status_code == 401


def test_7_7_a_wrong_token_is_also_401(vault):
    r = vault.publish(_artifact("Nope", "body"), token="not-the-token")
    assert r.status_code == 401


def test_7_8_writes_503_when_the_token_is_unset(vault, monkeypatch):
    """SPEC 7.8 / SPEC 4: unset must fail closed, never default open."""
    monkeypatch.setattr(main, "PUBLISH_TOKEN", "")
    for call in (
        lambda: vault.client.post("/api/publish"),
        lambda: vault.client.post("/api/reindex"),
        lambda: vault.client.delete("/api/ideas/anything"),
    ):
        r = call()
        assert r.status_code == 503, r.text
        assert "VAULT_TOKEN" in r.json()["detail"]


# ---------------------------------------------------------------- 7.9-7.10 security

def test_7_9_raw_carries_the_csp_sandbox_header(vault):
    """SPEC 7.9 / invariant 5. Omitting allow-same-origin is the whole point."""
    vault.publish(_artifact("Hostile", "body", slug="hostile"))
    r = vault.client.get("/raw/hostile")

    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert csp.startswith("sandbox")
    assert "allow-same-origin" not in csp, "that would defeat the unique-origin sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_7_10_detail_page_iframe_has_the_sandbox_attribute(vault):
    """SPEC 7.10 / invariant 5, defence in depth."""
    vault.publish(_artifact("Framed", "body", slug="framed"))
    body = vault.client.get("/i/framed").text

    assert "<iframe" in body
    assert 'sandbox="allow-scripts allow-popups allow-forms"' in body


def test_invariant_5_artifact_html_is_never_inlined_into_a_template(vault):
    """The boundary is the iframe. Artifact script must reach /raw/ and nowhere else."""
    marker = "XYZZY_ARTIFACT_SCRIPT_MARKER"
    html = (
        "<!DOCTYPE html><html><head><title>Live</title>"
        '<meta name="idea:slug" content="live"></head>'
        f"<body><script>var x = '{marker}';</script></body></html>"
    )
    vault.publish(html)

    assert marker in vault.client.get("/raw/live").text
    assert marker not in vault.client.get("/i/live").text
    assert marker not in vault.client.get("/").text


def test_hostile_metadata_is_escaped_in_the_chrome(vault):
    """Artifact-controlled strings reach vault templates. They must be escaped."""
    vault.publish(
        _artifact("Bad", "body", slug="bad", **{"idea:title": '"><script>alert(1)</script>'})
    )
    for path in ("/", "/i/bad"):
        body = vault.client.get(path).text
        assert "<script>alert(1)</script>" not in body, f"unescaped title in {path}"


# ---------------------------------------------------------------- 7.11 reindex

def test_7_11_deleting_the_database_and_reindexing_restores_every_row(vault):
    """SPEC 7.11 / invariant 1: files on disk are truth, the index is disposable.

    REGRESSION GUARD F6 -- currently 500s with "no such table: ideas" because
    db.init() runs only in the boot lifespan.
    """
    vault.publish(_artifact("One", "body one", slug="one"))
    vault.publish(_artifact("Two", "body two", slug="two"))
    assert len(vault.rows()) == 2

    vault.db_path.unlink()

    r = vault.client.post("/api/reindex", headers=vault.auth)
    assert r.status_code == 200, f"F6: reindex must rebuild a deleted index, got {r.text}"
    assert r.json()["indexed"] == 2

    slugs = sorted(row["slug"] for row in vault.rows())
    assert slugs == ["one", "two"]
    assert sorted(i["title"] for i in db.list_ideas()) == ["One", "Two"]


# ---------------------------------------------------------------- 7.12 visibility

def test_7_12_viewer_level_public_hides_private_ideas_everywhere(vault, monkeypatch):
    """SPEC 7.12. Index, detail AND raw must all filter."""
    vault.publish(_artifact("Secret", "body", slug="secret"))
    vault.publish(
        _artifact("Open", "body", slug="open", **{"idea:visibility": "public"})
    )

    monkeypatch.setattr(main, "VIEWER_LEVEL", "public")

    index = vault.client.get("/").text
    assert "Open" in index
    assert "Secret" not in index

    assert vault.client.get("/i/secret").status_code == 404
    assert vault.client.get("/raw/secret").status_code == 404
    assert vault.client.get("/i/open").status_code == 200
    assert vault.client.get("/raw/open").status_code == 200

    listed = [i["slug"] for i in vault.client.get("/api/ideas").json()["ideas"]]
    assert listed == ["open"]


def test_healthz_counts_everything_regardless_of_viewer_level(vault, monkeypatch):
    """By design: healthz is liveness, not a reader view."""
    vault.publish(_artifact("Hidden", "body", slug="hidden"))
    monkeypatch.setattr(main, "VIEWER_LEVEL", "public")
    assert vault.client.get("/healthz").json() == {"ok": True, "count": 1}


# ---------------------------------------------------------------- 7.13 limits

def test_7_13_oversized_upload_is_rejected_with_400_and_real_numbers(vault, monkeypatch):
    """SPEC 7.13 and SPEC 6: the error states the actual size and the limit."""
    monkeypatch.setattr(ingest, "MAX_BYTES", 512)
    r = vault.publish(_artifact("Huge", "x" * 4000))

    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "512" in detail, f"the limit must appear: {detail}"
    assert any(ch.isdigit() for ch in detail.replace("512", "")), "the actual size too"


def test_empty_upload_is_rejected_with_400(vault):
    r = vault.publish("")
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


# ---------------------------------------------------------------- 7.14 inbox

def test_7_14_drain_inbox_publishes_and_archives_and_leaves_a_bad_file(vault):
    """SPEC 7.14.

    Note: malformed HTML is NOT a bad file -- invariant 4 means it publishes with
    fallbacks. An EMPTY file is the one input that fails, so it is the one that
    must stay put. (This is finding F3, withdrawn as a spec problem.)
    """
    (vault.inbox / "good.html").write_text(_artifact("Good Inbox", "a fine body"))
    (vault.inbox / "junk.html").write_text("<<<>>> not really html &&& <div unclosed")
    (vault.inbox / "empty.html").write_text("")

    results = ingest.drain_inbox()

    actions = {r.get("file", r.get("slug")): r["action"] for r in results}
    assert actions.get("empty.html") == "failed"

    remaining = sorted(p.name for p in vault.inbox.glob("*.html"))
    assert remaining == ["empty.html"], "the bad file must be left in place"

    archived = sorted(p.name for p in (vault.inbox / "_ingested").glob("*.html"))
    assert archived == ["good.html", "junk.html"], "malformed still publishes"


# ---------------------------------------------------------------- failure modes

def test_row_without_a_file_returns_410_with_an_instruction(vault):
    """SPEC 6. The error says what happened AND what to do."""
    vault.publish(_artifact("Orphan", "body", slug="orphan"))
    (vault.content / "orphan.html").unlink()

    r = vault.client.get("/raw/orphan")
    assert r.status_code == 410
    assert "reindex" in r.json()["detail"].lower()


def test_unknown_slug_is_404_on_every_read_route(vault):
    for path in ("/i/nope", "/raw/nope"):
        assert vault.client.get(path).status_code == 404


def test_delete_removes_both_the_row_and_the_file(vault):
    vault.publish(_artifact("Doomed", "body", slug="doomed"))
    r = vault.client.delete("/api/ideas/doomed", headers=vault.auth)

    assert r.status_code == 200
    assert vault.rows() == []
    assert vault.files() == []


def test_delete_of_an_unknown_slug_is_404(vault):
    r = vault.client.delete("/api/ideas/ghost", headers=vault.auth)
    assert r.status_code == 404


def test_F6_reads_survive_the_index_being_deleted(vault):
    """REGRESSION GUARD F6, wider than SPEC 7.11.

    The index is disposable by design, so vault.db can vanish while the process
    is running. Before the fix, db.init() ran only in the boot lifespan, so every
    read raised "no such table: ideas" and GET / and GET /i/ returned 500.
    """
    vault.publish(_artifact("Alive", "body", slug="alive"))
    vault.db_path.unlink()

    assert vault.client.get("/").status_code == 200
    assert vault.client.get("/healthz").status_code == 200
    assert vault.client.get("/api/ideas").status_code == 200
    # The row is gone with the index, so this is a legitimate 404, not a 500.
    assert vault.client.get("/i/alive").status_code == 404

    r = vault.client.post("/api/reindex", headers=vault.auth)
    assert r.status_code == 200
    assert vault.client.get("/i/alive").status_code == 200


def test_F7_reindex_drops_rows_whose_artifact_is_gone(vault):
    """REGRESSION GUARD F7. reindex must be total, or the 410 advice is a lie.

    /raw/ answers 410 "Run POST /api/reindex" when a row has no file. If reindex
    only ever inserts, that instruction never clears the row and the user is
    told to run something that cannot help.
    """
    vault.publish(_artifact("Keeper", "body", slug="keeper"))
    vault.publish(_artifact("Doomed", "body", slug="doomed"))

    (vault.content / "doomed.html").unlink()  # removed outside the app
    assert vault.client.get("/raw/doomed").status_code == 410

    r = vault.client.post("/api/reindex", headers=vault.auth)
    assert r.status_code == 200
    assert r.json()["indexed"] == 1, "only the surviving artifact is indexed"

    assert [row["slug"] for row in vault.rows()] == ["keeper"]
    assert vault.client.get("/raw/doomed").status_code == 404, (
        "after the advice is followed the stale row is gone, so it is a 404 not a 410"
    )


def test_F8_token_comparison_is_constant_time(vault):
    """REGRESSION GUARD F8. SPEC 4: "constant comparison against VAULT_TOKEN".

    `!=` on str short-circuits at the first differing byte. Asserting on timing is
    flaky, so this asserts on the mechanism: require_token must route through
    secrets.compare_digest.
    """
    import inspect
    src = inspect.getsource(main.require_token)
    assert "compare_digest" in src, "SPEC 4 requires a constant-time comparison"

    # Behaviour must be unchanged by the mechanism.
    assert vault.publish(_artifact("T", "b"), token="wrong").status_code == 401
    assert vault.publish(_artifact("T", "b"), token=vault.token).status_code == 201


def test_F9_reindex_slugs_are_spec_valid_for_any_filename(vault):
    """REGRESSION GUARD F9. Files on disk are truth, and disk names are arbitrary.

    A restored backup or hand-copied artifact can be called anything. reindex used
    path.stem verbatim, so "My Notes.html" became the slug "My Notes" -- spaces and
    capitals in a URL, violating SPEC 2.3's [a-z0-9-] constraint.
    """
    body = "<html><head><title>T</title></head><body><p>body</p></body></html>"
    for name in ["A Capital File.html", "has spaces.html", "Unïcode Näme.html"]:
        (vault.content / name).write_text(body)

    r = vault.client.post("/api/reindex", headers=vault.auth)
    assert r.status_code == 200

    for row in vault.rows():
        slug = row["slug"]
        assert slug == slug.lower(), f"{slug!r} is not lowercased"
        assert all(c.isalnum() or c == "-" for c in slug), f"{slug!r} violates SPEC 2.3"
        assert slug.isascii(), f"{slug!r} is not ascii"
        # The real filename is still recorded, so /raw/ can serve it.
        assert (vault.content / row["filename"]).exists()


def test_F9_reindex_does_not_rewrite_normal_slugs(vault):
    """slugify must be idempotent, or reindex would churn every published slug."""
    vault.publish(_artifact("Normal Idea", "body"))
    before = [r["slug"] for r in vault.rows()]
    vault.client.post("/api/reindex", headers=vault.auth)
    assert [r["slug"] for r in vault.rows()] == before == ["normal-idea"]


def test_F10_uppercase_extensions_are_indexed(vault):
    """REGRESSION GUARD F10. Path.glob is case-sensitive on Linux.

    A restored file named RESTORED.HTML was skipped entirely, so an artifact on
    disk never appeared anywhere -- an invariant 1 failure.
    """
    (vault.content / "RESTORED.HTML").write_text(
        "<html><head><title>Restored</title></head><body><p>body</p></body></html>"
    )
    r = vault.client.post("/api/reindex", headers=vault.auth)

    assert r.json()["indexed"] == 1, "the .HTML file must be seen"
    assert [row["slug"] for row in vault.rows()] == ["restored"]
    assert vault.client.get("/raw/restored").status_code == 200


def test_slug_cannot_escape_the_content_directory(vault):
    """slugify is the only thing standing between idea:slug and the filesystem."""
    for evil in ["../../etc/passwd", "..\\..\\windows", "/absolute/path", "a/../../b"]:
        r = vault.publish(
            _artifact("Evil", "body", slug=evil), filename="evil.html"
        )
        assert r.status_code in (200, 201), r.text
        slug = r.json()["slug"]
        assert "/" not in slug and "\\" not in slug and ".." not in slug, slug
        written = (vault.content / f"{slug}.html").resolve()
        assert written.parent == vault.content.resolve(), f"escaped to {written}"


def test_F11_a_permanently_bad_inbox_file_is_reported_once(vault):
    """REGRESSION GUARD F11.

    A bad file stays in the inbox by design (SPEC 6) and the poller runs every
    VAULT_POLL_SECONDS, so re-reporting it every pass means ~29,000 identical log
    lines a day from one empty file.
    """
    (vault.inbox / "empty.html").write_text("")

    first = ingest.drain_inbox()
    assert [r["action"] for r in first] == ["failed"]

    for _ in range(5):
        assert ingest.drain_inbox() == [], "an unchanged bad file must not re-report"

    assert (vault.inbox / "empty.html").exists(), "but it must still be left in place"


def test_F11_fixing_a_bad_inbox_file_in_place_is_picked_up(vault):
    """The quiet must not be permanent -- SPEC 6's recovery is "inspect and fix"."""
    bad = vault.inbox / "fixme.html"
    bad.write_text("")
    assert [r["action"] for r in ingest.drain_inbox()] == ["failed"]
    assert ingest.drain_inbox() == []

    bad.write_text(_artifact("Fixed Now", "a real body this time"))

    results = ingest.drain_inbox()
    assert [r["action"] for r in results] == ["created"]
    assert not bad.exists(), "it published, so it moved to _ingested/"
    assert (vault.inbox / "_ingested" / "fixme.html").exists()


def test_F12_a_typo_in_viewer_level_is_rejected_loudly(vault):
    """REGRESSION GUARD F12.

    VAULT_VIEWER_LEVEL was read straight into a dict subscript, so `publik` booted
    fine and then raised KeyError on every page. main.py now validates at import;
    this covers the resolver it validates through.
    """
    import pytest as _pytest

    for level in ("private", "internal", "public"):
        assert db.visible_at(level)

    with _pytest.raises(ValueError) as exc:
        db.visible_at("publik")
    message = str(exc.value)
    assert "publik" in message, "say what was wrong"
    assert "private" in message and "internal" in message, "and what the options are"


def test_F12_the_visibility_ladder_has_one_definition(vault):
    """Two copies of the ladder is how the query filter and route guard drift."""
    import inspect
    assert "VISIBLE_AT" not in inspect.getsource(main._allowed)
    assert inspect.getsource(main._allowed).count("db.visible_at") == 1

    for level, expected in [
        ("public", ("public",)),
        ("internal", ("public", "internal")),
        ("private", ("public", "internal", "private")),
    ]:
        assert db.visible_at(level) == expected


def test_F13_unicode_digits_are_not_a_valid_date(vault):
    """REGRESSION GUARD F13. SPEC 2.3 calls the date check strict; `\\d` is not.

    `\\d` matches every Unicode Nd codepoint, so Arabic-Indic and full-width digits
    passed and landed in a column SPEC 2.2 declares as ISO-8601 -- where they sort
    above every real date.
    """
    import datetime as dt
    from app import metadata
    today = dt.date.today().isoformat()
    for bad in ["٢٠٢٠-٠١-٠١",
                "２０２６-０８-２５"]:
        m = metadata.parse(f"<html><head><meta name='idea:date' content='{bad}'></head></html>")
        assert m.date == today, f"{bad!r} must be rejected, got {m.date!r}"
        assert m.date.isascii()


def test_F14_a_non_ascii_explicit_slug_is_stable_across_edits(vault):
    """REGRESSION GUARD F14 / invariant 3.

    A non-ASCII explicit slug reduces to "" under slugify, and the hash fallback was
    seeded from html[:2000]. Editing anything in the first 2000 bytes therefore
    changed the slug, so one idea became a duplicate row and a second file.
    """
    body_a = "<html><head><meta name='idea:slug' content='идея'><title>T</title></head><body><p>first</p></body></html>"
    body_b = "<html><head><meta name='idea:slug' content='идея'><title>T</title></head><body><p>edited right at the front</p></body></html>"

    first = vault.publish(body_a)
    second = vault.publish(body_b)

    assert first.json()["slug"] == second.json()["slug"], "same idea, same slug"
    assert second.json()["action"] == "updated"
    assert len(vault.rows()) == 1, "invariant 3: never a duplicate row"
    assert len(vault.files()) == 1, "invariant 3: never a second file"

    # And a different non-ASCII slug is still a different idea.
    other = vault.publish(body_a.replace("идея", "другая"))
    assert other.json()["slug"] != first.json()["slug"]


def test_F15_an_interrupted_write_cannot_destroy_the_existing_artifact(vault):
    """REGRESSION GUARD F15 / invariant 1.

    write_bytes truncates first, so a failure mid-write left a half-written
    artifact and nothing to restore from. The write is now atomic, so a failure
    leaves the previous bytes completely intact.
    """
    keep = "the original bytes that must survive a failed write"
    vault.publish(_artifact("Atomic", keep, slug="atomic"))
    dest = vault.content / "atomic.html"

    real_replace = ingest.os.replace
    def boom(src, dst):
        raise OSError(28, "No space left on device")
    ingest.os.replace = boom
    try:
        with __import__("pytest").raises(OSError):
            ingest.publish(_artifact("Atomic", "replacement", slug="atomic").encode())
    finally:
        ingest.os.replace = real_replace

    assert keep in dest.read_text(), "the original artifact must be untouched"
    # No debris left behind, and nothing the indexer would pick up.
    assert vault.files() == ["atomic.html"]
    assert [p.name for p in ingest._artifact_files(vault.content)] == ["atomic.html"]


def test_F16_a_corrupt_index_is_replaced_rather_than_crash_looping(vault):
    """REGRESSION GUARD F16. SPEC 6: "Index corrupt or deleted -> Automatic"."""
    vault.publish(_artifact("Survivor", "body", slug="survivor"))

    vault.db_path.write_bytes(b"this is not a sqlite database, it is garbage")

    db.init()  # previously raised sqlite3.DatabaseError: file is not a database
    r = vault.client.post("/api/reindex", headers=vault.auth)

    assert r.status_code == 200
    assert [row["slug"] for row in vault.rows()] == ["survivor"]


def test_F17_a_racing_first_publish_does_not_500(vault):
    """REGRESSION GUARD F17 / invariant 3.

    upsert's SELECT ran on its own connection with no lock, so the inbox poller and
    an HTTP publish could both see "no row" for one slug and both INSERT. The
    second raised IntegrityError -> 500 with the artifact on disk and no row.
    """
    meta = type("M", (), {"slug": "racer", "title": "Racer", "description": "",
                          "tags": [], "date": "2026-01-01", "visibility": "private"})()
    assert db.upsert(meta, filename="racer.html", size=1, sha="aaa") == "created"
    # A second writer that also saw "no row" takes the INSERT path again.
    with db.conn() as c:
        c.execute("DELETE FROM ideas WHERE 0")  # keep the row, force a fresh connection
    assert db.upsert(meta, filename="racer.html", size=1, sha="bbb") in ("created", "updated")
    assert len(vault.rows()) == 1, "one slug, one row, whichever path ran"


def test_F18_an_oversized_inbox_file_is_rejected_from_stat_not_after_reading(vault, monkeypatch):
    """REGRESSION GUARD F18. publish() checks len(bytes), which is already too late."""
    monkeypatch.setattr(ingest, "MAX_BYTES", 256)
    (vault.inbox / "huge.html").write_text("x" * 5000)

    reads = []
    real_read = pathlib.Path.read_bytes
    monkeypatch.setattr(
        pathlib.Path, "read_bytes",
        lambda self: (reads.append(self.name), real_read(self))[1],
    )
    results = ingest.drain_inbox()

    assert [r["action"] for r in results] == ["failed"]
    assert "256" in results[0]["error"]
    assert "huge.html" not in reads, "the file must not be read into memory at all"
    assert (vault.inbox / "huge.html").exists(), "and it stays for inspection"


def test_F20_a_non_ascii_token_is_401_not_500(vault):
    """REGRESSION GUARD F20 -- a regression introduced by the F8 fix.

    secrets.compare_digest raises TypeError on a str holding any non-ASCII
    character, so comparing the header value directly let an unauthenticated
    caller turn a 401 into a 500.

    This calls require_token directly rather than going through the test client,
    because httpx refuses to send a non-ASCII header. A raw client is under no
    such obligation: Starlette decodes header bytes as latin-1, so the bytes
    "Bearer t\xf6k\xe9n" on the wire arrive here as a non-ASCII str. Verified
    over a real socket against uvicorn: 500 before this fix, 401 after.
    """
    import pytest as _pytest
    from fastapi import HTTPException

    for bad in ["Bearer t\xf6k\xe9n", "Bearer \u043f\u0430\u0440\u043e\u043b\u044c", "Bearer \xff"]:
        with _pytest.raises(HTTPException) as exc:
            main.require_token(authorization=bad)
        assert exc.value.status_code == 401, f"{bad!r} must be 401, not a crash"

    main.require_token(authorization=f"Bearer {vault.token}")  # real one still passes


def test_F20_a_non_ascii_vault_token_still_authenticates(monkeypatch):
    """The same crash would have broken every write for a non-ASCII VAULT_TOKEN."""
    import pytest as _pytest
    from fastapi import HTTPException

    monkeypatch.setattr(main, "PUBLISH_TOKEN", "p\xe4ssw\xf6rd-\xfcnicode")

    with _pytest.raises(HTTPException) as exc:
        main.require_token(authorization="Bearer wrong")
    assert exc.value.status_code == 401

    main.require_token(authorization="Bearer p\xe4ssw\xf6rd-\xfcnicode")  # must not raise


def test_F20_comparison_is_still_constant_time_over_bytes():
    import inspect
    src = inspect.getsource(main.require_token)
    assert "compare_digest" in src, "SPEC 4 requires a constant-time comparison"
    assert 'encode("utf-8")' in src, "and it must compare bytes, not str"


def test_F21_reindex_does_not_orphan_an_artifact_published_while_it_runs(vault):
    """REGRESSION GUARD F21 -- a regression introduced by the F7 prune fix.

    reindex scanned the directory, then pruned every row not in that snapshot. The
    inbox poller runs every VAULT_POLL_SECONDS, so a publish landing mid-scan was
    routine -- and its row was deleted while its file stayed on disk, leaving the
    artifact invisible until some later reindex happened to catch it.
    """
    vault.publish(_artifact("Existing", "body", slug="existing"))

    real_scan = ingest._artifact_files
    def scan_then_publish(directory):
        found = real_scan(directory)
        if directory == ingest.CONTENT_DIR and not getattr(scan_then_publish, "done", False):
            scan_then_publish.done = True
            # A concurrent publish lands after the scan, before the prune.
            ingest.publish(_artifact("Racer", "body", slug="racer").encode())
        return found

    ingest._artifact_files = scan_then_publish
    try:
        vault.client.post("/api/reindex", headers=vault.auth)
    finally:
        ingest._artifact_files = real_scan

    slugs = sorted(row["slug"] for row in vault.rows())
    assert "racer" in slugs, "the concurrently-published artifact was orphaned"
    assert (vault.content / "racer.html").exists()
    assert vault.client.get("/raw/racer").status_code == 200
    assert sorted(slugs) == ["existing", "racer"]


def test_F19_publish_does_not_block_the_event_loop(vault):
    """REGRESSION GUARD F19 -- confirmed by the sweep with a 65s measurement.

    BeautifulSoup cost scales with document size and VAULT_MAX_BYTES allows 15 MB,
    so a legal upload froze every other route, /healthz included. Asserting on
    wall-clock would be flaky, so this asserts the mechanism: the CPU work must be
    dispatched off the loop, the way watch_inbox already does it.
    """
    import inspect
    src = inspect.getsource(main.api_publish)
    assert "to_thread" in src, "publish must not run inline on the event loop"
    assert "ingest.publish" in src

    # And it still behaves.
    r = vault.publish(_artifact("Threaded", "body", slug="threaded"))
    assert r.status_code == 201
    assert r.json()["slug"] == "threaded"
    assert vault.client.get("/raw/threaded").status_code == 200
