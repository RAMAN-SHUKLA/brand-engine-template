"""Resolve post media to local files.

`images` on a post may be local repo paths or http(s) URLs. URLs are
downloaded once into a temp cache so Bluesky's uploadBlob and LinkedIn's
image upload can read bytes from disk.
"""
from __future__ import annotations
import hashlib
import os
import tempfile
from pathlib import Path

import requests

from ..paths import ROOT

CACHE = Path(tempfile.gettempdir()) / "brand-engine-media"
MAX_BYTES = 1_000_000  # Bluesky's image blob limit; LinkedIn allows far more


def _download(url: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()
    ext = ".png" if "opengraph-image" in url or url.endswith(".png") else ".jpg"
    dest = CACHE / f"{name}{ext}"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    r = requests.get(url, timeout=60)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"media download failed {r.status_code} for {url}")
    data = r.content
    if len(data) > MAX_BYTES:
        data = _shrink(data, MAX_BYTES)
    dest.write_bytes(data)
    return dest


def _shrink(data: bytes, limit: int) -> bytes:
    """Re-encode an oversized image as JPEG, stepping quality down until it fits."""
    try:
        from io import BytesIO
        from PIL import Image
    except ImportError:  # Pillow not installed: return as-is and let the platform reject it loudly
        return data
    im = Image.open(BytesIO(data)).convert("RGB")
    for q in (88, 82, 76, 70, 62):
        buf = BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= limit:
            return buf.getvalue()
    return buf.getvalue()


def resolve_media(paths: list[str] | None) -> list[str]:
    out: list[str] = []
    for p in paths or []:
        if p.startswith(("http://", "https://")):
            out.append(str(_download(p)))
        elif os.path.isabs(p):
            out.append(p)
        else:
            out.append(str(ROOT / p))
    return out
