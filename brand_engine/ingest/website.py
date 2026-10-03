"""Fetch your own site pages and reduce them to title/description/text."""
from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup


def fetch_page(url: str, limit: int = 6000) -> dict:
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (brand-engine)"}, timeout=30)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return {"url": url, "ok": False, "error": str(e)[:200]}
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        t.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    md = soup.find("meta", attrs={"name": "description"})
    og = soup.find("meta", attrs={"property": "og:image"})
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return {"url": url, "ok": True, "title": title, "description": md.get("content") if md else "",
            "og_image": og.get("content") if og else None, "text": text[:limit]}


def fetch_site(urls: list[str]) -> dict:
    return {"pages": [fetch_page(u) for u in urls]}
