"""Bluesky posting over the AT Protocol (https://docs.bsky.app). Free, no API tier.

Auth: handle + app password (Settings -> Privacy and security -> App passwords). Never the main password.
Limits: 300 graphemes of text, up to 4 images (<= 1 MB each, JPEG/PNG/WebP). Links must be declared as
"facets" with UTF-8 byte offsets or they render as plain text; this module builds them automatically.
"""
from __future__ import annotations
import datetime as dt
import mimetypes
import os
import re
from pathlib import Path
import requests

PDS = "https://bsky.social/xrpc"
MAX_CHARS = 300
URL_RE = re.compile(r"https?://[^\s<>()\[\]\"']+")
TAG_RE = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_]{1,63})")


def login(handle: str | None = None, app_password: str | None = None) -> dict:
    handle = (handle or os.environ.get("BLUESKY_HANDLE", "")).lstrip("@").strip()
    pw = app_password or os.environ.get("BLUESKY_APP_PASSWORD", "")
    if not handle or not pw:
        raise RuntimeError("BLUESKY_HANDLE / BLUESKY_APP_PASSWORD missing in .env")
    r = requests.post(f"{PDS}/com.atproto.server.createSession",
                      json={"identifier": handle, "password": pw}, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Bluesky login failed {r.status_code}: {r.text[:300]}")
    s = r.json()
    return {"jwt": s["accessJwt"], "did": s["did"], "handle": s.get("handle", handle)}


def _facets(text: str) -> list[dict]:
    """Link and hashtag facets with byte offsets (AT Protocol requires UTF-8 byte indices)."""
    facets = []
    b = text.encode("utf-8")

    def byte_span(start_char: int, end_char: int) -> tuple[int, int]:
        return len(text[:start_char].encode("utf-8")), len(text[:end_char].encode("utf-8"))

    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:!?")
        s, e = byte_span(m.start(), m.start() + len(url))
        facets.append({"index": {"byteStart": s, "byteEnd": e},
                       "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]})
    for m in TAG_RE.finditer(text):
        s, e = byte_span(m.start(), m.end())
        facets.append({"index": {"byteStart": s, "byteEnd": e},
                       "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": m.group(1)}]})
    assert len(b) >= 0
    return facets


def upload_blob(session: dict, path: str | Path) -> dict:
    path = Path(path)
    data = path.read_bytes()
    if len(data) > 1_000_000:
        raise RuntimeError(f"{path.name} is {len(data)//1024} KB; Bluesky images must be under 1 MB. Resize it first.")
    ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    r = requests.post(f"{PDS}/com.atproto.repo.uploadBlob", data=data, timeout=60,
                      headers={"Authorization": f"Bearer {session['jwt']}", "Content-Type": ctype})
    if r.status_code >= 300:
        raise RuntimeError(f"Bluesky uploadBlob failed {r.status_code}: {r.text[:300]}")
    return r.json()["blob"]


def delete_post(session: dict, uri: str) -> None:
    rkey = uri.rsplit("/", 1)[-1]
    r = requests.post(f"{PDS}/com.atproto.repo.deleteRecord", timeout=30,
                      headers={"Authorization": f"Bearer {session['jwt']}"},
                      json={"repo": session["did"], "collection": "app.bsky.feed.post", "rkey": rkey})
    if r.status_code >= 300:
        raise RuntimeError(f"Bluesky delete failed {r.status_code}: {r.text[:300]}")


def pin_post(session: dict, uri: str, cid: str) -> dict:
    """Pin a post to the profile (app.bsky.actor.profile.pinnedPost)."""
    r = requests.get(f"{PDS}/com.atproto.repo.getRecord", timeout=30,
                     params={"repo": session["did"], "collection": "app.bsky.actor.profile", "rkey": "self"},
                     headers={"Authorization": f"Bearer {session['jwt']}"})
    if r.status_code == 200:
        rec, swap = r.json()["value"], r.json().get("cid")
    else:
        rec, swap = {"$type": "app.bsky.actor.profile"}, None
    rec["pinnedPost"] = {"uri": uri, "cid": cid}
    body = {"repo": session["did"], "collection": "app.bsky.actor.profile", "rkey": "self", "record": rec}
    if swap:
        body["swapRecord"] = swap
    r = requests.post(f"{PDS}/com.atproto.repo.putRecord", json=body, timeout=30,
                      headers={"Authorization": f"Bearer {session['jwt']}"})
    if r.status_code >= 300:
        raise RuntimeError(f"Bluesky pin failed {r.status_code}: {r.text[:300]}")
    return r.json()


def post(text: str, images: list[str | Path] | None = None, alts: list[str] | None = None,
         session: dict | None = None, reply_to: dict | None = None) -> dict:
    """reply_to: a previous post() result (its id/cid); the reply is attached to that post's thread."""
    if len(text) > MAX_CHARS:
        raise RuntimeError(f"Bluesky post is {len(text)} chars; limit is {MAX_CHARS}")
    session = session or login()
    record = {"$type": "app.bsky.feed.post", "text": text,
              "createdAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
              "langs": ["en"]}
    facets = _facets(text)
    if facets:
        record["facets"] = facets
    if reply_to:
        ref = {"uri": reply_to["id"], "cid": reply_to["cid"]}
        record["reply"] = {"root": reply_to.get("root") or ref, "parent": ref}
    if images:
        imgs = []
        for i, p in enumerate(images[:4]):
            imgs.append({"alt": (alts[i] if alts and i < len(alts) else Path(p).stem.replace("-", " ")),
                         "image": upload_blob(session, p)})
        record["embed"] = {"$type": "app.bsky.embed.images", "images": imgs}
    r = requests.post(f"{PDS}/com.atproto.repo.createRecord", timeout=60,
                      headers={"Authorization": f"Bearer {session['jwt']}"},
                      json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record})
    if r.status_code >= 300:
        raise RuntimeError(f"Bluesky createRecord failed {r.status_code}: {r.text[:300]}")
    d = r.json()
    rkey = d["uri"].rsplit("/", 1)[-1]
    return {"platform": "bluesky", "id": d["uri"], "cid": d.get("cid"),
            "url": f"https://bsky.app/profile/{session['handle']}/post/{rkey}", "published": True}
