"""Weekly batches of short social posts (LinkedIn, Threads, Bluesky).

A batch lives in data/batches/<ISO week>/posts.json and is rendered to review.md for you to read.
`python cli.py batch new` writes one with Claude from your niche and facts; you can also write or edit
posts.json by hand. Posts that react to news carry the item they react to (title + URL), and every post
lists the knowledge-base fact ids it leans on.

Lifecycle per post: draft -> approved (or dropped) -> queued -> posted
"""
from __future__ import annotations
import datetime as dt
import re
from pathlib import Path

from ..paths import DATA, get_niche, load_json, save_json, write_text

BATCHES = DATA / "batches"
BANNED_DEFAULT = ["revolutionary", "game-changing", "cutting-edge", "unlock the power", "delve",
                  "in today's fast-paced world"]


def week_id(d: dt.date | None = None) -> str:
    d = d or dt.date.today()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def batch_dir(week: str) -> Path:
    p = BATCHES / week
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_batch(week: str) -> dict:
    b = load_json(batch_dir(week) / "posts.json")
    if not b:
        raise SystemExit(f"No batch for {week}. Existing: {', '.join(list_batches()) or 'none'}")
    return b


def list_batches() -> list[str]:
    return sorted(p.name for p in BATCHES.iterdir() if (p / "posts.json").exists()) if BATCHES.exists() else []


LIMITS = {"linkedin": 3000, "bluesky": 300, "threads": 500}


def check_post(p: dict, cfg: dict, sig_len: int) -> list[str]:
    w = []
    text = p.get("text", "")
    platform = (p.get("platforms") or ["linkedin"])[0]
    limit = LIMITS.get(platform, 3000)
    if platform != "linkedin":
        sig_len = len(cfg["publish"].get(platform, {}).get("signature", "") or "")
    if len(text) + sig_len + 2 > limit:
        w.append(f"too long: {len(text)} chars + signature exceeds {platform}'s {limit}")
    if platform == "linkedin" and len(text) < 200:
        w.append("very short (<200 chars)")
    first = text.split("\n")[0]
    if platform == "linkedin" and len(first) > 210:
        w.append(f"hook line is {len(first)} chars; LinkedIn truncates around 200")
    if "[FILL" in text:
        w.append("contains [FILL] placeholder")
    low = text.lower()
    niche = get_niche(cfg)
    for b in niche["banned_phrases"] or BANNED_DEFAULT:
        if b.lower() in low:
            w.append(f"banned phrase: {b}")
    for m in niche["avoid_mentions"]:
        if m.lower() in low:
            w.append(f"mentions '{m}' which must not appear")
    if p.get("kind", "news") == "news" and not p.get("source_url"):
        w.append("news post without a source_url")
    if re.search(r"\*\*|^#{1,3} ", text, flags=re.M):
        w.append("markdown formatting present; LinkedIn shows it literally")
    return w


def save_batch(batch: dict, cfg: dict | None = None) -> Path:
    if cfg is None:
        from ..paths import load_config
        cfg = load_config()
    sig = cfg["publish"].get("linkedin", {}).get("signature", "")
    for p in batch["posts"]:
        p["warnings"] = check_post(p, cfg, len(sig))
        p["chars"] = len(p.get("text", ""))
    folder = batch_dir(batch["week"])
    save_json(folder / "posts.json", batch)
    write_text(folder / "review.md", render_review(batch, sig))
    return folder


def render_review(batch: dict, sig: str) -> str:
    counts: dict[str, int] = {}
    for p in batch["posts"]:
        counts[p.get("status", "draft")] = counts.get(p.get("status", "draft"), 0) + 1
    lines = [f"# Weekly batch {batch['week']}", "",
             f"Created {batch.get('created', '')}. {len(batch['posts'])} posts. Status: "
             + ", ".join(f"{k}={v}" for k, v in counts.items()), "",
             "Every post is published with this signature appended:", "", f"> {sig}", "",
             "How to act on this file: reply with the post ids to drop or change, then run",
             f"`python cli.py batch approve --week {batch['week']} [--drop P03,P09]` and "
             f"`python cli.py batch schedule --week {batch['week']}`.", ""]
    if batch.get("news"):
        lines += ["## News items used this week", ""]
        for n in batch["news"]:
            lines.append(f"- **{n['title']}** - {n['url']}" + (f" ({n['date']})" if n.get("date") else ""))
        lines.append("")
    lines += ["## Posts", ""]
    for p in batch["posts"]:
        lines += [f"### {p['id']}  [{p.get('status', 'draft')}]  {','.join(p.get('platforms') or ['linkedin'])}  "
                  f"{p.get('pillar', '')}  {p.get('chars', len(p['text']))} chars", ""]
        if p.get("source_title"):
            lines.append(f"*Reacting to:* {p['source_title']} - {p.get('source_url', '')}")
        if p.get("facts_used"):
            lines.append(f"*Grounded in:* {', '.join(p['facts_used'])}")
        if p.get("claims_to_verify"):
            lines.append("*Check before approving:* " + "; ".join(p["claims_to_verify"]))
        if p.get("image_idea"):
            lines.append(f"*Image idea:* {p['image_idea']}")
        if p.get("warnings"):
            lines.append("*Warnings:* " + "; ".join(p["warnings"]))
        lines += ["", "```", p["text"], "```", ""]
    return "\n".join(lines)


def approve(week: str, only: list[str] | None = None, drop: list[str] | None = None,
            ignore_warnings: bool = False) -> dict:
    from ..paths import load_config
    cfg = load_config()
    b = load_batch(week)
    drop = set(drop or [])
    only = set(only) if only else None
    counts = {"approved": 0, "dropped": 0, "blocked": 0, "untouched": 0}
    for p in b["posts"]:
        if p["id"] in drop:
            p["status"] = "dropped"; counts["dropped"] += 1
        elif p.get("status") == "draft" and (only is None or p["id"] in only):
            hard = [w for w in check_post(p, cfg, len(cfg["publish"].get("linkedin", {}).get("signature", "")))
                    if "too long" in w or "[FILL]" in w or "without a source" in w]
            if hard and not ignore_warnings:
                counts["blocked"] += 1
            else:
                p["status"] = "approved"; counts["approved"] += 1
        else:
            counts["untouched"] += 1
    save_batch(b, cfg)
    return counts


def schedule(week: str, days: list[str], times: list[str] | str, start: dt.datetime | None = None,
             platform: str = "linkedin") -> list[dict]:
    """Queue approved posts of this batch whose platforms include `platform`, into that platform's free slots."""
    from ..publish import queue as Q
    b = load_batch(week)
    todo = [p for p in b["posts"] if p.get("status") == "approved" and platform in (p.get("platforms") or ["linkedin"])]
    if not todo:
        return []
    slots = Q.next_slots(days, times, start, len(todo), Q.busy_slots(platform))
    items = []
    for p, when in zip(todo, slots):
        items.append(Q.add_short(week, p["id"], when, (platform,)))
        p["status"] = "queued"
        p["scheduled_at"] = when.isoformat(timespec="minutes")
    save_batch(b)
    return items


def new_batch(week: str, news: list[dict], posts: list[dict], cfg: dict) -> Path:
    for i, p in enumerate(posts, 1):
        p.setdefault("id", f"P{i:02d}")
        p.setdefault("status", "draft")
        p.setdefault("platforms", ["linkedin"])
        p.setdefault("kind", "news" if p.get("source_url") else "evergreen")
    batch = {"week": week, "created": dt.datetime.now().isoformat(timespec="minutes"), "news": news, "posts": posts}
    return save_batch(batch, cfg)
