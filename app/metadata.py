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


def _meta(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return tag["content"].strip()
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
    slug = slugify(explicit_slug or title, fallback_seed=html[:2000])

    description = (
        _meta(soup, "idea:description")
        or _meta(soup, "description")
        or _first_prose(soup)
    )

    raw_tags = _meta(soup, "idea:tags") or _meta(soup, "keywords")
    tags = [t.strip().lower() for t in re.split(r"[,;]", raw_tags) if t.strip()][:8]

    date = _meta(soup, "idea:date")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
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
