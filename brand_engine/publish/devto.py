"""Dev.to (Forem) publishing. Docs: https://developers.forem.com/api/v1#tag/articles/operation/createArticle"""
from __future__ import annotations
import os
import re
import requests

API = "https://dev.to/api/articles"


def sanitize_tags(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        t = re.sub(r"[^a-z0-9]", "", t.lower())
        if t and t not in out:
            out.append(t)
    return out[:4]


def update(article_id: int, body_markdown: str | None = None, title: str | None = None,
           description: str | None = None, api_key: str | None = None) -> dict:
    """Edit an existing Dev.to article in place (same URL, same reactions)."""
    key = api_key or os.environ.get("DEVTO_API_KEY")
    article = {k: v for k, v in {"body_markdown": body_markdown, "title": title,
                                 "description": description[:150] if description else None}.items() if v is not None}
    r = requests.put(f"{API}/{article_id}", json={"article": article}, timeout=60,
                     headers={"api-key": key, "Content-Type": "application/json",
                              "Accept": "application/vnd.forem.api-v1+json"})
    if r.status_code >= 300:
        raise RuntimeError(f"Dev.to update error {r.status_code}: {r.text[:500]}")
    d = r.json()
    return {"platform": "devto", "id": d.get("id"), "url": d.get("url"), "updated": True}


def publish(title: str, body_markdown: str, tags: list[str], published: bool = False,
            canonical_url: str | None = None, description: str | None = None,
            series: str | None = None, api_key: str | None = None, main_image: str | None = None) -> dict:
    key = api_key or os.environ.get("DEVTO_API_KEY")
    if not key:
        raise RuntimeError("DEVTO_API_KEY missing in .env")
    article = {"title": title, "body_markdown": body_markdown, "published": published,
               "tags": sanitize_tags(tags)}
    if canonical_url:
        article["canonical_url"] = canonical_url
    if description:
        article["description"] = description[:150]
    if series:
        article["series"] = series
    if main_image:
        article["main_image"] = main_image
    r = requests.post(API, json={"article": article}, timeout=60,
                      headers={"api-key": key, "Content-Type": "application/json",
                               "Accept": "application/vnd.forem.api-v1+json"})
    if r.status_code >= 300:
        raise RuntimeError(f"Dev.to error {r.status_code}: {r.text[:500]}")
    d = r.json()
    return {"platform": "devto", "id": d.get("id"), "url": d.get("url"), "published": published,
            "dashboard": "https://dev.to/dashboard"}
