"""SPEC section 7, requirements 1-3: the metadata contract and its fallbacks.

These are unit tests against metadata.parse() -- no app, no database. Invariant 4
says parsing never raises, so every hostile input here must return an IdeaMeta.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app import metadata


def test_7_1_full_meta_block_is_parsed(vault_html):
    """7.1 -- a complete idea:* block wins over everything else."""
    m = metadata.parse(
        vault_html(
            title="Ignored By Meta",
            meta={
                "idea:title": "Revelator Intelligence Layer",
                "idea:slug": "revelator-intelligence-layer",
                "idea:tags": "architecture, world-models, ops",
                "idea:description": "Four-layer design replacing middle management.",
                "idea:date": "2026-08-25",
                "idea:visibility": "internal",
            },
        ),
        filename="whatever.html",
    )
    assert m.title == "Revelator Intelligence Layer"
    assert m.slug == "revelator-intelligence-layer"
    assert m.slug_was_explicit is True
    assert m.tags == ["architecture", "world-models", "ops"]
    assert m.description == "Four-layer design replacing middle management."
    assert m.date == "2026-08-25"
    assert m.visibility == "internal"


# ---------------------------------------------------------------- 7.2 fallbacks

def test_7_2_title_falls_back_through_the_whole_chain(vault_html):
    """idea:title -> <title> -> <h1> -> filename -> "Untitled idea"."""
    assert metadata.parse(
        vault_html(title="From Title Tag", meta={"idea:title": "From Meta"})
    ).title == "From Meta"

    assert metadata.parse(vault_html(title="From Title Tag", h1="From H1")).title == (
        "From Title Tag"
    )
    assert metadata.parse(vault_html(title=None, h1="From H1")).title == "From H1"
    assert metadata.parse(
        vault_html(title=None, h1=None), filename="my_great-idea.html"
    ).title == "My Great Idea"
    assert metadata.parse(vault_html(title=None, h1=None), filename="").title == (
        "Untitled idea"
    )


def test_7_2_no_head_at_all_still_parses(vault_html):
    """The explicit case SPEC 7.2 calls out: a file with no <head>."""
    m = metadata.parse(
        "<html><body><h1>Bare Document</h1>"
        "<p>A paragraph long enough to serve as the description fallback here.</p>"
        "</body></html>",
        filename="bare.html",
    )
    assert m.title == "Bare Document"
    assert m.slug == "bare-document"
    assert m.description.startswith("A paragraph long enough")
    assert m.visibility == "private"


def test_7_2_description_falls_back_through_the_whole_chain(vault_html):
    assert metadata.parse(
        vault_html(meta={"idea:description": "From idea meta", "description": "From plain"})
    ).description == "From idea meta"

    assert metadata.parse(
        vault_html(meta={"description": "From plain description meta"})
    ).description == "From plain description meta"

    # First prose element over 40 chars wins; the short one is skipped.
    m = metadata.parse(
        "<html><body><p>Too short.</p>"
        "<p>This paragraph is comfortably longer than forty characters.</p>"
        "</body></html>"
    )
    assert m.description == "This paragraph is comfortably longer than forty characters."

    # Nothing usable at all -> empty string, not None.
    assert metadata.parse("<html><body><p>Short.</p></body></html>").description == ""


def test_7_2_tags_split_on_both_separators_and_lowercase(vault_html):
    m = metadata.parse(vault_html(meta={"idea:tags": "Alpha, BETA; Gamma ,delta"}))
    assert m.tags == ["alpha", "beta", "gamma", "delta"]

    # keywords is the documented second choice.
    assert metadata.parse(vault_html(meta={"keywords": "One;Two"})).tags == ["one", "two"]

    # Absent -> empty list.
    assert metadata.parse(vault_html()).tags == []


def test_7_2_tags_are_capped_at_eight(vault_html):
    m = metadata.parse(vault_html(meta={"idea:tags": ",".join(f"t{i}" for i in range(30))}))
    assert len(m.tags) == 8, "SPEC 2.3 caps tags at 8"


def test_7_2_date_must_be_iso_or_it_falls_back_to_today(vault_html):
    assert metadata.parse(vault_html(meta={"idea:date": "2020-01-02"})).date == "2020-01-02"
    today = dt.date.today().isoformat()
    for bad in ["25-08-2026", "2026-8-5", "not a date", "", "2026-08-25T10:00:00"]:
        assert metadata.parse(vault_html(meta={"idea:date": bad})).date == today, bad


def test_7_2_visibility_enum_is_honoured_and_bad_values_default_private(vault_html):
    for good in ["private", "internal", "public"]:
        assert metadata.parse(vault_html(meta={"idea:visibility": good})).visibility == good
    # Case-insensitive, per the .lower() in parse().
    assert metadata.parse(vault_html(meta={"idea:visibility": "PUBLIC"})).visibility == "public"
    for bad in ["secret", "", "world-readable", "prívate"]:
        assert metadata.parse(
            vault_html(meta={"idea:visibility": bad})
        ).visibility == "private", bad


def test_7_2_title_and_description_are_capped(vault_html):
    m = metadata.parse(vault_html(meta={"idea:title": "T" * 500}))
    assert len(m.title) <= 200, "SPEC 2.3 caps title at 200"
    m = metadata.parse(vault_html(meta={"idea:description": "D" * 900}))
    assert len(m.description) <= 400, "SPEC 2.3 caps description at 400"


# ---------------------------------------------------------------- 7.3 never raises

@pytest.mark.parametrize(
    "junk",
    [
        "",
        "   ",
        "not html at all",
        "<<<>>> &&& <div unclosed",
        "<html><head><meta name=idea:title></head></html>",
        "<html><title></title><h1></h1><body></body></html>",
        "<meta name='idea:tags' content=',,,;;;'>",
        "\x00\x01\x02 binary-ish \xff",
        "<html>" + "<div>" * 500 + "deep" + "</div>" * 500 + "</html>",
        "<html><title>" + "中文 \U0001f600 עברית" + "</title></html>",
    ],
)
def test_7_3_malformed_input_never_raises(junk):
    """Invariant 4. Every one of these must return a usable IdeaMeta."""
    m = metadata.parse(junk, filename="junk.html")
    assert isinstance(m, metadata.IdeaMeta)
    assert m.slug, "a slug is always produced"
    assert m.title, "a title is always produced"
    assert m.visibility in metadata.VISIBILITIES


def test_slugify_degrades_to_a_hash_when_nothing_survives():
    """A title of pure punctuation or non-latin script has no ascii left."""
    s = metadata.slugify("!!! ???", fallback_seed="seed")
    assert s.startswith("idea-") and len(s) > 5


def test_slug_is_capped_and_charset_constrained(vault_html):
    m = metadata.parse(vault_html(meta={"idea:slug": "A" * 300}))
    assert len(m.slug) <= 72, "SPEC 2.3 caps slug at 72"
    m = metadata.parse(vault_html(meta={"idea:slug": "Has Spaces & Symbols!"}))
    assert all(c.isalnum() or c == "-" for c in m.slug), m.slug
    assert m.slug == m.slug.lower()


# ---------------------------------------------------------------- F22 quoted markup

def test_F22_metadata_inside_quoted_markup_is_ignored(vault_html):
    """REGRESSION GUARD F22 / invariant 1.

    html.parser does not treat <pre> as raw text, so an unescaped <meta> inside one
    parses as a live tag. An artifact documenting the metadata contract therefore
    claimed the slug from its own example -- and an explicit slug bypasses the
    collision guard by design (SPEC 2.4), so it overwrote the idea it named and
    flipped its visibility. Measured before the fix: a how-to page destroyed a
    private artifact called q3-board-deck.
    """
    doc = (
        "<html><head><title>How To Use The Vault</title></head><body>"
        "<h1>How to publish</h1><p>Add this block to your artifact, please:</p>"
        "<pre>"
        '<meta name="idea:slug" content="q3-board-deck">'
        '<meta name="idea:visibility" content="public">'
        '<meta name="idea:tags" content="stolen, tags">'
        "</pre></body></html>"
    )
    m = metadata.parse(doc, filename="howto.html")

    assert m.slug == "how-to-use-the-vault", f"slug came from the example: {m.slug!r}"
    assert m.slug_was_explicit is False, "an example must not count as an explicit slug"
    assert m.visibility == "private", "visibility must not be escalated by an example"
    assert m.tags == [], f"tags came from the example: {m.tags!r}"


def test_F22_every_quoted_element_is_covered(vault_html):
    for element in sorted(metadata.QUOTED_MARKUP):
        doc = (
            f"<html><head><title>Doc</title></head><body><{element}>"
            f'<meta name="idea:slug" content="hijacked">'
            f'<meta name="idea:visibility" content="public">'
            f"</{element}></body></html>"
        )
        m = metadata.parse(doc)
        assert m.slug == "doc", f"<{element}> leaked a slug: {m.slug!r}"
        assert m.visibility == "private", f"<{element}> escalated visibility"


def test_F22_real_metadata_outside_quoted_markup_still_works(vault_html):
    """The fix must not cost any legitimate placement."""
    # In <head>, the documented form.
    m = metadata.parse(vault_html(meta={"idea:slug": "in-head", "idea:visibility": "public"}))
    assert m.slug == "in-head" and m.visibility == "public" and m.slug_was_explicit

    # In <body>, which SPEC 2.3 does not forbid.
    m = metadata.parse(
        "<html><body><meta name='idea:slug' content='in-body'>"
        "<h1>T</h1></body></html>"
    )
    assert m.slug == "in-body" and m.slug_was_explicit

    # A bare meta block with no <head> at all -- html.parser synthesises none, which
    # is exactly why the fix is not "only look inside <head>".
    m = metadata.parse(
        "<meta name='idea:slug' content='no-head-at-all'>"
        "<meta name='idea:title' content='No Head'>"
        "<p>body</p>"
    )
    assert m.slug == "no-head-at-all", "a headless artifact must keep its metadata"
    assert m.title == "No Head"


def test_F22_a_real_tag_wins_over_a_quoted_one_regardless_of_order(vault_html):
    """A page that documents the contract AND uses it must get its own value."""
    doc = (
        "<html><head>"
        '<pre><meta name="idea:slug" content="from-the-example"></pre>'
        '<meta name="idea:slug" content="the-real-one">'
        "<title>T</title></head><body><p>b</p></body></html>"
    )
    assert metadata.parse(doc).slug == "the-real-one"
