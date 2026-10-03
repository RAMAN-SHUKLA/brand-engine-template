"""Fetch the author's own public LinkedIn post pages (no login) and store them like the data export would.

Use when you don't have the official data export yet: paste post URLs into data/linkedin_post_urls.txt
(one per line) and run `python cli.py ingest --linkedin-urls`. Public post pages expose the full text in
the page body and og:description; the exact timestamp is decoded from the activity id (top 41 bits = ms).
Only the author's own posts should be listed here.
"""
from __future__ import annotations
import datetime as dt
import re
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

from ..paths import DATA, load_json, save_json, write_text

URLS_FILE = DATA / "linkedin_post_urls.txt"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36")


def activity_time(url: str) -> str | None:
    m = re.search(r"activity-(\d{15,})", url)
    if not m:
        return None
    ms = int(m.group(1)) >> 22
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).astimezone().isoformat(timespec="minutes")


def fetch_post(url: str) -> dict:
    out = {"url": url, "date": activity_time(url), "text": None, "ok": False}
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}, timeout=30)
        out["status"] = r.status_code
        if r.status_code != 200:
            return out
        s = BeautifulSoup(r.text, "html.parser")
        body = s.select_one(".attributed-text-segment-list__content")
        text = body.get_text("\n", strip=True) if body else None
        if not text:
            md = s.find("meta", attrs={"property": "og:description"})
            text = md.get("content") if md else None
        if text:
            out["text"] = re.sub(r"\n{3,}", "\n\n", text).strip()
            out["ok"] = True
        imgs = [i.get("src") for i in s.select("img") if i.get("src") and "media.licdn.com" in i.get("src")]
        out["media_url"] = imgs[0] if imgs else None
        title = s.find("meta", attrs={"property": "og:title"})
        out["title"] = title.get("content") if title else None
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
    return out


def fetch_all(urls: list[str], delay: float = 1.5) -> list[dict]:
    seen, posts = set(), []
    for u in urls:
        key = re.search(r"activity-(\d+)", u)
        key = key.group(1) if key else u
        if key in seen:
            continue
        seen.add(key)
        posts.append(fetch_post(u.strip()))
        time.sleep(delay)
    posts.sort(key=lambda p: p.get("date") or "", reverse=True)
    return posts


def merge_into_linkedin_json(posts: list[dict]) -> dict:
    """Write/merge data/linkedin.json in the same shape linkedin_export.load_export produces."""
    li = load_json(DATA / "linkedin.json") or {"source": "public post pages", "tables": {}, "articles": [],
                                                 "profile": {}, "files_seen": [], "stats": {}}
    existing = {re.search(r"activity-(\d+)", p.get("url") or "").group(1): p
                for p in li.get("posts", []) if re.search(r"activity-(\d+)", p.get("url") or "")}
    for p in posts:
        if not p.get("ok"):
            continue
        aid = re.search(r"activity-(\d+)", p["url"]).group(1)
        existing[aid] = {"date": p["date"], "url": p["url"], "text": p["text"], "shared_url": None,
                         "media_url": p.get("media_url"), "visibility": "PUBLIC"}
    li["posts"] = sorted(existing.values(), key=lambda p: p.get("date") or "", reverse=True)
    li["media_urls"] = sorted({p["media_url"] for p in li["posts"] if p.get("media_url")})
    li["stats"] = {**li.get("stats", {}), "posts": len(li["posts"])}
    save_json(DATA / "linkedin.json", li)
    dump = ["# Your LinkedIn posts (fetched from public pages)", ""]
    for p in li["posts"]:
        dump += [f"## {(p.get('date') or '')[:10]}  {p['url']}", "", p["text"] or "", ""]
    write_text(DATA / "linkedin_posts.md", "\n".join(dump))
    return li
