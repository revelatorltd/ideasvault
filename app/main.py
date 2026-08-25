"""Ideas Vault — publish a self-contained HTML artifact by dropping it in a folder."""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, ingest

PUBLISH_TOKEN = os.environ.get("VAULT_TOKEN", "")
VIEWER_LEVEL = os.environ.get("VAULT_VIEWER_LEVEL", "private")  # what a reader may see
RAW_ORIGIN = os.environ.get("VAULT_RAW_ORIGIN", "")  # e.g. https://raw.ideas.example.com
POLL_SECONDS = int(os.environ.get("VAULT_POLL_SECONDS", 3))

HERE = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))


def require_token(authorization: str = Header(default="")) -> None:
    if not PUBLISH_TOKEN:
        raise HTTPException(503, "VAULT_TOKEN is not set, so publishing is disabled.")
    presented = authorization.removeprefix("Bearer ").strip()
    # SPEC 4: "constant comparison against VAULT_TOKEN". `!=` on str short-circuits
    # at the first differing byte and leaks the length of the shared prefix.
    if not secrets.compare_digest(presented, PUBLISH_TOKEN):
        raise HTTPException(401, "That token is not valid for publishing.")


async def watch_inbox() -> None:
    while True:
        try:
            for r in await asyncio.to_thread(ingest.drain_inbox):
                print(f"[inbox] {r.get('action')}: {r.get('slug') or r.get('file')}")
        except Exception as exc:
            print(f"[inbox] scan failed: {exc}")
        await asyncio.sleep(POLL_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    ingest.CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    ingest.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    if not db.list_ideas():
        print(f"[boot] empty index, reindexed {ingest.reindex()} artifacts from disk")
    task = asyncio.create_task(watch_inbox())
    yield
    task.cancel()


app = FastAPI(title="Ideas Vault", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


# ---------------------------------------------------------------- reading

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    ideas = db.list_ideas(VIEWER_LEVEL)
    tags: dict[str, int] = {}
    for i in ideas:
        for t in i["tags"]:
            tags[t] = tags.get(t, 0) + 1
    return templates.TemplateResponse(
        request, "index.html",
        {"ideas": ideas, "tags": sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))},
    )


@app.get("/i/{slug}", response_class=HTMLResponse)
def detail(request: Request, slug: str):
    idea = db.get(slug)
    if not idea or idea["visibility"] not in _allowed():
        raise HTTPException(404, "No idea with that name.")
    raw = f"{RAW_ORIGIN.rstrip('/')}/raw/{slug}" if RAW_ORIGIN else f"/raw/{slug}"
    return templates.TemplateResponse(request, "detail.html",
                                      {"idea": idea, "raw_url": raw})


@app.get("/raw/{slug}")
def raw(slug: str):
    idea = db.get(slug)
    if not idea or idea["visibility"] not in _allowed():
        raise HTTPException(404, "No idea with that name.")
    path = ingest.CONTENT_DIR / idea["filename"]
    if not path.exists():
        raise HTTPException(410, "The index has this idea but its file is missing. "
                                 "Run POST /api/reindex.")
    # Unique-origin sandbox: artifact scripts run, but cannot reach the vault.
    return FileResponse(path, media_type="text/html", headers={
        "Content-Security-Policy": "sandbox allow-scripts allow-popups allow-forms",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-cache",
    })


@app.get("/api/ideas")
def api_ideas():
    return {"ideas": db.list_ideas(VIEWER_LEVEL)}


@app.get("/healthz")
def healthz():
    return {"ok": True, "count": len(db.list_ideas("private"))}


# ---------------------------------------------------------------- writing

@app.post("/api/publish", dependencies=[Depends(require_token)])
async def api_publish(file: UploadFile = File(...)):
    try:
        result = ingest.publish(await file.read(), filename=file.filename or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result, status_code=201 if result["action"] == "created" else 200)


@app.post("/api/reindex", dependencies=[Depends(require_token)])
def api_reindex():
    return {"indexed": ingest.reindex()}


@app.delete("/api/ideas/{slug}", dependencies=[Depends(require_token)])
def api_delete(slug: str):
    idea = db.get(slug)
    if not idea:
        raise HTTPException(404, "No idea with that name.")
    (ingest.CONTENT_DIR / idea["filename"]).unlink(missing_ok=True)
    db.delete(slug)
    return {"deleted": slug}


def _allowed() -> tuple[str, ...]:
    return {"public": ("public",),
            "internal": ("public", "internal"),
            "private": ("public", "internal", "private")}[VIEWER_LEVEL]
