"""
Ideas Vault MCP server — lets Claude publish and search the vault from a chat.

    pip install fastmcp httpx
    VAULT_URL=https://ideas.example.com VAULT_TOKEN=... python mcp/server.py

Then add it as a custom connector in Claude. Three tools, deliberately narrow:
publish_idea (write), list_ideas (read), get_idea_url (read).
"""

from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP

VAULT_URL = os.environ["VAULT_URL"].rstrip("/")
VAULT_TOKEN = os.environ["VAULT_TOKEN"]
AUTH = {"Authorization": f"Bearer {VAULT_TOKEN}"}

mcp = FastMCP("ideas-vault")

META_BLOCK = """<meta name="idea:title" content="{title}">
<meta name="idea:slug" content="{slug}">
<meta name="idea:tags" content="{tags}">
<meta name="idea:description" content="{description}">
<meta name="idea:date" content="{date}">
<meta name="idea:visibility" content="{visibility}">"""


@mcp.tool()
def publish_idea(
    html: str,
    title: str,
    description: str,
    tags: list[str],
    slug: str = "",
    date: str = "",
    visibility: str = "private",
) -> dict:
    """Publish a self-contained HTML artifact to the vault and return its URL.

    Injects the metadata block into <head> so the file stays self-describing.
    Reusing a slug replaces that idea in place instead of creating a duplicate.
    """
    import datetime
    import re

    block = META_BLOCK.format(
        title=title.replace('"', "'"),
        slug=slug or "",
        tags=", ".join(tags),
        description=description.replace('"', "'"),
        date=date or datetime.date.today().isoformat(),
        visibility=visibility,
    )
    if re.search(r"<head[^>]*>", html, re.I):
        html = re.sub(r"(<head[^>]*>)", r"\1\n" + block, html, count=1, flags=re.I)
    else:
        html = f"<!DOCTYPE html><html><head>\n{block}\n</head><body>{html}</body></html>"

    files = {"file": ("idea.html", html.encode(), "text/html")}
    r = httpx.post(f"{VAULT_URL}/api/publish", headers=AUTH, files=files, timeout=30)
    r.raise_for_status()
    result = r.json()
    result["full_url"] = f"{VAULT_URL}{result['url']}"
    return result


@mcp.tool()
def list_ideas(tag: str = "", search: str = "") -> list[dict]:
    """List filed ideas, optionally narrowed by tag or a text match."""
    r = httpx.get(f"{VAULT_URL}/api/ideas", headers=AUTH, timeout=15)
    r.raise_for_status()
    ideas = r.json()["ideas"]
    if tag:
        ideas = [i for i in ideas if tag.lower() in [t.lower() for t in i["tags"]]]
    if search:
        s = search.lower()
        ideas = [i for i in ideas
                 if s in i["title"].lower() or s in i["description"].lower()]
    return [{k: i[k] for k in ("slug", "title", "description", "tags", "date")}
            for i in ideas]


@mcp.tool()
def get_idea_url(slug: str) -> str:
    """Return the shareable URL for one idea."""
    return f"{VAULT_URL}/i/{slug}"


if __name__ == "__main__":
    mcp.run()
