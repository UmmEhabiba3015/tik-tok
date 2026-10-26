import secrets
from contextlib import asynccontextmanager

from fastapi import Cookie, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel

from app import db, tiktok
from app.config import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="TikTok Posting Service", lifespan=lifespan)


@app.exception_handler(tiktok.TikTokError)
async def tiktok_error_handler(_, exc: tiktok.TikTokError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/health")
def health():
    return {"status": "ok", "connected": db.get_token() is not None}


# ---------- Auth ----------

@app.get("/auth/login")
def login():
    state = secrets.token_urlsafe(16)
    resp = RedirectResponse(tiktok.authorize_url(state))
    resp.set_cookie("tiktok_state", state, httponly=True, secure=True, max_age=600)
    return resp


@app.get("/auth/callback")
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    tiktok_state: str | None = Cookie(default=None),
):
    if error:
        raise HTTPException(400, f"TikTok login failed: {error} {error_description or ''}")
    if not code or not state or state != tiktok_state:
        raise HTTPException(400, "Invalid OAuth state or missing code")
    data = tiktok.exchange_code(code)
    return {"connected": True, "open_id": data["open_id"], "scope": data.get("scope")}


# ---------- Posts ----------

class VideoPost(BaseModel):
    file: str  # filename inside the media/ folder
    caption: str = ""


@app.get("/creator-info")
def creator_info():
    return tiktok.creator_info()


@app.post("/posts/video")
def post_video(body: VideoPost):
    media_dir = settings.media_dir.resolve()
    path = (media_dir / body.file).resolve()
    if not path.is_relative_to(media_dir) or not path.is_file():
        raise HTTPException(404, f"File not found in media/: {body.file}")
    publish_id = tiktok.post_video(path, body.caption)
    return {"publish_id": publish_id}


@app.get("/posts/{publish_id}")
def post_status(publish_id: str):
    return tiktok.post_status(publish_id)


# ---------- Pages required by the TikTok app registration ----------

@app.get("/terms", response_class=HTMLResponse)
def terms():
    return """<h1>Terms of Service</h1>
<p>This is an internal proof-of-concept service used to publish content to TikTok
on behalf of its owner. It is not offered to the public.</p>"""


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return """<h1>Privacy Policy</h1>
<p>This service stores only the TikTok OAuth tokens needed to post on behalf of the
connected account. No data is shared with third parties. Tokens can be revoked at
any time from TikTok's settings.</p>"""


@app.get("/", response_class=HTMLResponse)
def home():
    return "<h1>TikTok Posting Service</h1><p><a href='/terms'>Terms</a> | <a href='/privacy'>Privacy</a></p>"


@app.get("/{filename}.txt", response_class=PlainTextResponse)
def verification_file(filename: str):
    """Serves TikTok domain-verification files dropped into verification/."""
    path = settings.verification_dir / f"{filename}.txt"
    if "/" in filename or not path.is_file():
        raise HTTPException(404)
    return path.read_text()
