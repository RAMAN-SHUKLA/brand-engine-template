"""Threads posting via Meta's Threads API (https://developers.facebook.com/docs/threads).

Auth is fundamentally different from Bluesky: there's no handle+password login here. You need a
long-lived Threads access token tied to a Threads PROFESSIONAL account, with scopes
`threads_basic` + `threads_content_publish`. Getting that token is a one-time OAuth flow you do
yourself in a browser (Meta requires the account owner's own login) -- see README.md "Threads
setup" for the exact steps. Once THREADS_ACCESS_TOKEN is in .env / the GitHub secret, this module
behaves the same way bluesky.py does: login() once, call post() many times.

Limits: 500 characters (see queue.CHAR_LIMITS). One image per post here (Threads also supports
carousels; this module doesn't build those). Unlike Bluesky's upload_blob (raw bytes), Threads
takes an `image_url` it fetches itself, so images must already be public URLs (no upload step).

Publishing a post is two calls, the same "container" pattern Instagram's Graph API uses:
  1. POST /{threads_user_id}/threads   -> creates a container, returns a creation_id
  2. POST /{threads_user_id}/threads_publish -> publishes that container, returns the media id
A container referencing an image can take a few seconds to become ready (Meta has to fetch the
image); _wait_until_ready polls for that before step 2, the same fix as linkedin.upload_image's
wait for AVAILABLE.
"""
from __future__ import annotations
import os
import time
import requests

API = "https://graph.threads.com/v1.0"
MAX_CHARS = 500


def login(token: str | None = None) -> dict:
    """Resolve the token and the account's numeric Threads user id (both needed on every call)."""
    token = token or os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("THREADS_ACCESS_TOKEN missing in .env")
    r = requests.get(f"{API}/me", params={"fields": "id,username", "access_token": token}, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Threads /me failed {r.status_code}: {r.text[:300]} "
                           "(token needs scopes: threads_basic threads_content_publish)")
    d = r.json()
    return {"token": token, "user_id": d["id"], "username": d.get("username")}


def _wait_until_ready(creation_id: str, token: str, tries: int = 10, delay: float = 2.0) -> None:
    """Container creation is async, especially with an image_url Meta has to fetch first."""
    for _ in range(tries):
        r = requests.get(f"{API}/{creation_id}", params={"fields": "status", "access_token": token}, timeout=30)
        if r.status_code == 200:
            status = r.json().get("status")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise RuntimeError(f"Threads container {creation_id} failed to process")
        time.sleep(delay)
    # Not confirmed ready after all tries -- publish anyway; most containers finish in a few
    # seconds per Meta's own docs, so this is a generous wait, not a hard requirement.


def post(text: str, images: list[str] | None = None, alts: list[str] | None = None,
         session: dict | None = None) -> dict:
    """images: public http(s) URLs -- Threads fetches them itself,
    no byte upload like Bluesky's upload_blob. Only the first image is used here."""
    if len(text) > MAX_CHARS:
        raise RuntimeError(f"Threads post is {len(text)} chars; limit is {MAX_CHARS}")
    session = session or login()
    token, user_id = session["token"], session["user_id"]
    params = {"access_token": token, "text": text}
    if images:
        params["media_type"] = "IMAGE"
        params["image_url"] = images[0]
    else:
        params["media_type"] = "TEXT"
    r = requests.post(f"{API}/{user_id}/threads", data=params, timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"Threads container create failed {r.status_code}: {r.text[:300]}")
    creation_id = r.json()["id"]
    if images:
        _wait_until_ready(creation_id, token)
    r2 = requests.post(f"{API}/{user_id}/threads_publish",
                       data={"creation_id": creation_id, "access_token": token}, timeout=60)
    if r2.status_code >= 300:
        raise RuntimeError(f"Threads publish failed {r2.status_code}: {r2.text[:300]}")
    media_id = r2.json()["id"]
    r3 = requests.get(f"{API}/{media_id}", params={"fields": "permalink", "access_token": token}, timeout=30)
    url = r3.json().get("permalink") if r3.status_code == 200 else None
    return {"platform": "threads", "id": media_id,
            "url": url or f"https://www.threads.com/@{session.get('username', '')}/post/{media_id}",
            "published": True}
