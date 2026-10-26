"""Thin wrapper around the TikTok Login Kit + Content Posting API (v2)."""

import math
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app import db
from app.config import settings

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
SCOPES = "user.info.basic,video.upload,video.publish"

CHUNK_SIZE = 10 * 1024 * 1024  # TikTok allows 5MB-64MB chunks
MIN_CHUNK = 5 * 1024 * 1024

CONTENT_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}


class TikTokError(Exception):
    pass


# ---------- OAuth ----------

def authorize_url(state: str) -> str:
    params = {
        "client_key": settings.tiktok_client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": settings.redirect_uri,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(extra: dict) -> dict:
    resp = httpx.post(
        f"{API}/oauth/token/",
        data={
            "client_key": settings.tiktok_client_key,
            "client_secret": settings.tiktok_client_secret,
            **extra,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    data = resp.json()
    if "access_token" not in data:
        raise TikTokError(f"Token request failed: {data}")
    return data


def exchange_code(code: str) -> dict:
    data = _token_request(
        {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.redirect_uri,
        }
    )
    db.save_token(data)
    return data


def get_access_token() -> str:
    """Return a valid access token, refreshing it if it is (nearly) expired."""
    token = db.get_token()
    if not token:
        raise TikTokError("No TikTok account connected. Visit /auth/login first.")
    if token["expires_at"] - 60 > time.time():
        return token["access_token"]
    data = _token_request(
        {"grant_type": "refresh_token", "refresh_token": token["refresh_token"]}
    )
    db.save_token(data)
    return data["access_token"]


# ---------- Content Posting ----------

def _post(path: str, body: dict | None = None) -> dict:
    resp = httpx.post(
        f"{API}{path}",
        json=body or {},
        headers={
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json; charset=UTF-8",
        },
    )
    payload = resp.json()
    error = payload.get("error", {})
    if error.get("code") != "ok":
        raise TikTokError(f"{path} failed: {error}")
    return payload["data"]


def creator_info() -> dict:
    return _post("/post/publish/creator_info/query/")


def _chunk_plan(size: int) -> tuple[int, int]:
    """Return (chunk_size, total_chunk_count) following TikTok's rules:
    files under 5MB go in one chunk; otherwise the last chunk absorbs the remainder."""
    if size < MIN_CHUNK:
        return size, 1
    return CHUNK_SIZE, max(1, math.floor(size / CHUNK_SIZE))


def post_video(path: Path, caption: str, privacy_level: str = "SELF_ONLY") -> str:
    """Direct-post a local video file. Returns TikTok's publish_id."""
    content_type = CONTENT_TYPES.get(path.suffix.lower())
    if not content_type:
        raise TikTokError(f"Unsupported video type: {path.suffix}")

    size = path.stat().st_size
    chunk_size, chunk_count = _chunk_plan(size)

    # TikTok requires querying creator info before every post.
    creator_info()

    data = _post(
        "/post/publish/video/init/",
        {
            "post_info": {"title": caption, "privacy_level": privacy_level},
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": chunk_count,
            },
        },
    )

    with path.open("rb") as f:
        for i in range(chunk_count):
            start = i * chunk_size
            # last chunk takes everything that is left
            end = size - 1 if i == chunk_count - 1 else start + chunk_size - 1
            f.seek(start)
            chunk = f.read(end - start + 1)
            resp = httpx.put(
                data["upload_url"],
                content=chunk,
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                },
                timeout=300,
            )
            if resp.status_code not in (200, 201, 206):
                raise TikTokError(f"Chunk {i} upload failed: {resp.status_code} {resp.text}")

    return data["publish_id"]


def post_status(publish_id: str) -> dict:
    return _post("/post/publish/status/fetch/", {"publish_id": publish_id})
