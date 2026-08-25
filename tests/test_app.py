"""SPEC section 7, requirements 4-14, plus regression guards for the confirmed
defects F1, F2, F4 and F6 recorded in .claude/notes/orientation.md.

Tests are written against the SPEC, not against current behaviour. The F-marked
tests are expected to fail until their fix unit lands -- that is the point of
writing them first.
"""

from __future__ import annotations

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
