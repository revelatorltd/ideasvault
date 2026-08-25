"""
Metadata contract.

Everything the vault needs lives INSIDE the HTML file, so a single artifact is the
only thing you ever manage. Preferred form (add this block to any artifact):

    <meta name="idea:title"       content="Revelator Intelligence Layer">
    <meta name="idea:slug"        content="revelator-intelligence-layer">
    <meta name="idea:tags"        content="architecture, world-models, ops">
    <meta name="idea:description" content="Four-layer design replacing middle management.">
    <meta name="idea:date"        content="2026-08-25">
    <meta name="idea:visibility"  content="private">

Every field has a fallback, so a file with none of this still publishes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

VISIBILITIES = {"private", "internal", "public"}
DEFAULT_VISIBILITY = "private"


@dataclass
class IdeaMeta:
    slug: str
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    date: str = ""
    visibility: str = DEFAULT_VISIBILITY
    slug_was_explicit: bool = False


def slugify(text: str, fallback_seed: str = "") -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)[:72].strip("-")
    if not text:
        text = "idea-" + hashlib.sha1(fallback_seed.encode()).hexdigest()[:8]
    return text


# Elements whose contents are markup being *displayed*, not markup being *applied*.
# html.parser does not treat these as raw text the way it does <script>/<style>, so
# an unescaped <meta> tag inside one is parsed as a live tag. That let an artifact
# which merely DOCUMENTS the metadata contract claim another idea's slug -- and
# because an explicit slug bypasses the collision guard by design (SPEC 2.4), the
# documented example silently overwrote the idea it named.
QUOTED_MARKUP = {"pre", "code", "textarea", "template", "xmp"}


def _meta(soup: BeautifulSoup, name: str) -> str:
    """First idea:* value that is real metadata rather than a displayed example.

    Deliberately not restricted to <head>: html.parser does not synthesise one, so
    an artifact that opens with a bare meta block and no <head> wrapper would lose
    all its metadata. Excluding quoted markup is the narrower rule -- the only
    artifacts whose behaviour changes are the ones that were exploitable.
    """
    for tag in soup.find_all("meta", attrs={"name": name}):
        if any(parent.name in QUOTED_MARKUP for parent in tag.parents):
            continue
        content = (tag.get("content") or "").strip()
        if content:
            return content
    return ""


def _first_prose(soup: BeautifulSoup, limit: int = 240) -> str:
    for el in soup.find_all(["p", "h2", "li"]):
        text = " ".join(el.get_text(" ", strip=True).split())
        if len(text) >= 40:
            return text[:limit]
    return ""


def parse(html: str, filename: str = "") -> IdeaMeta:
    """Parse an artifact into an IdeaMeta. Never raises on messy input."""
    soup = BeautifulSoup(html, "html.parser")

    title = (
        _meta(soup, "idea:title")
        or (soup.title.get_text(strip=True) if soup.title else "")
        or (soup.h1.get_text(" ", strip=True) if soup.h1 else "")
        or re.sub(r"\.html?$", "", filename).replace("-", " ").replace("_", " ").title()
        or "Untitled idea"
    )
    title = " ".join(title.split())[:200]

    explicit_slug = _meta(soup, "idea:slug")
    # Seed the hash fallback from the explicit slug when there is one. Seeding it
    # from the body meant a non-ASCII slug (Cyrillic, CJK, Hebrew) reduced to "" and
    # then hashed html[:2000] -- so editing anything in the first 2000 bytes changed
    # the slug, producing a duplicate row and a second file for one idea, against
    # invariant 3. Seeded from the slug it is stable across edits and still distinct
    # per idea.
    slug = slugify(
        explicit_slug or title,
        fallback_seed=explicit_slug or html[:2000],
    )

    description = (
        _meta(soup, "idea:description")
        or _meta(soup, "description")
        or _first_prose(soup)
    )

    raw_tags = _meta(soup, "idea:tags") or _meta(soup, "keywords")
    tags = [t.strip().lower() for t in re.split(r"[,;]", raw_tags) if t.strip()][:8]

    date = _meta(soup, "idea:date")
    # [0-9], not \d: \d is Unicode-aware and matches every Nd codepoint, so
    # Arabic-Indic and full-width digits passed this "strict format check" and
    # landed in the date column, where they sort above every real ISO date.
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date or ""):
        date = dt.date.today().isoformat()

    visibility = _meta(soup, "idea:visibility").lower()
    if visibility not in VISIBILITIES:
        visibility = DEFAULT_VISIBILITY

    return IdeaMeta(
        slug=slug,
        title=title,
        description=" ".join(description.split())[:400],
        tags=tags,
        date=date,
        visibility=visibility,
        slug_was_explicit=bool(explicit_slug),
    )
