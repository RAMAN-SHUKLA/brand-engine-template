"""Pull public GitHub data: profile, repos, READMEs. Unauthenticated works (60 req/h)."""
from __future__ import annotations
import os
import re
import time
import requests

API = "https://api.github.com"


def _headers(raw: bool = False) -> dict:
    h = {"Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
         "User-Agent": "brand-engine"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _get(url: str, raw: bool = False, params: dict | None = None):
    r = requests.get(url, headers=_headers(raw), params=params, timeout=30)
    if r.status_code == 403 and "rate limit" in r.text.lower():
        raise RuntimeError("GitHub rate limit hit. Set GITHUB_TOKEN in .env and retry.")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.text if raw else r.json()


def clean_readme(md: str, limit: int = 7000) -> str:
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)          # images
    md = re.sub(r"<img[^>]*>", "", md, flags=re.I)         # html images
    md = re.sub(r"<[^>]+>", "", md)                        # other html
    md = re.sub(r"^[\s▀-▟─-╿█░╗╔╝╚║═╦╩╬╠╣]+$", "", md, flags=re.M)  # ascii art
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md[:limit]


def first_paragraph(md: str) -> str:
    md = re.sub(r"```.*?```", "", md, flags=re.S)             # fenced code / mermaid
    md = re.sub(r"\[\]\([^)]*\)", "", md)                      # leftover badge links
    for block in re.split(r"\n\s*\n", md):
        b = re.sub(r"^>\s?", "", block.strip(), flags=re.M).strip()   # blockquotes
        b = re.sub(r"^\*\*(.+?)\*\*$", r"\1", b, flags=re.S).strip()  # bold-only paragraphs
        if len(b) < 60 or b.startswith(("#", "[", "|", "-", "*", "!", "<")):
            continue
        if "subgraph" in b or "-->" in b or "|:--" in b or "localhost" in b or "&nbsp;" in b:
            continue
        if b.startswith(("→", "->", "$", "pip ", "npm ", "git ", "Or ")):
            continue
        if "`" in b and len(b) < 250:          # short paragraphs built around a command/path
            continue
        return re.sub(r"\s+", " ", b)[:400]
    return ""


def live_links(md: str) -> list[str]:
    urls = re.findall(r"https?://[^\s)\]>\"'`]+", md)
    keep = []
    for u in urls:
        u = u.rstrip("*.,;:!?")
        if any(bad in u for bad in ("github.com", "shields.io", "badge", "img.", "licdn", "typescriptlang",
                                    "nextjs.org", "tailwindcss", "console.groq", "python.org", "opensource.org",
                                    "localhost", "127.0.0.1", "0.0.0.0", "example.com",
                                    # vendor/console links are not live demos
                                    "mistral.ai", "supabase.com", "makersuite", "google.com", "openai.com",
                                    "anthropic.com", "huggingface.co", "vercel.com", "railway.com", "render.com",
                                    "console.", "docs.", "cloud.", "your-project", "supabase.co")):
            continue
        if u not in keep:
            keep.append(u)
    return keep[:6]


def fetch_github(user: str, featured: list[str], max_readmes: int = 12) -> dict:
    profile = _get(f"{API}/users/{user}") or {}
    repos = []
    page = 1
    while True:
        batch = _get(f"{API}/users/{user}/repos", params={"per_page": 100, "page": page, "sort": "updated"}) or []
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    repos = [r for r in repos if not r.get("fork")]
    order = {name.lower(): i for i, name in enumerate(featured)}
    repos.sort(key=lambda r: (order.get(r["name"].lower(), 999), r["pushed_at"]), reverse=False)

    out_repos = []
    readme_budget = max_readmes
    for r in repos:
        item = {
            "name": r["name"], "url": r["html_url"], "description": r.get("description"),
            "language": r.get("language"), "stars": r.get("stargazers_count", 0),
            "topics": r.get("topics", []), "created_at": r.get("created_at"), "pushed_at": r.get("pushed_at"),
            "homepage": r.get("homepage"), "featured": r["name"].lower() in order,
        }
        if readme_budget > 0 and (item["featured"] or r.get("description")):
            md = _get(f"{API}/repos/{user}/{r['name']}/readme", raw=True)
            if md:
                cleaned = clean_readme(md)
                item["readme"] = cleaned
                item["summary"] = first_paragraph(cleaned)
                item["live_links"] = live_links(md)
            readme_budget -= 1
            time.sleep(0.2)
        out_repos.append(item)

    return {
        "user": user,
        "profile": {k: profile.get(k) for k in ("login", "name", "bio", "public_repos", "followers",
                                                "following", "blog", "location", "created_at", "html_url")},
        "repos": out_repos,
    }
