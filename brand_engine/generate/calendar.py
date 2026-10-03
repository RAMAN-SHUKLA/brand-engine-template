"""Content calendar: deterministic topics from your pillars and projects, optionally expanded by Claude."""
from __future__ import annotations
import datetime as dt
import re

from ..paths import CALENDAR_PATH, KB_PATH, get_niche, load_json, save_json

# Evergreen post shapes that work in any niche; {topic} is config.yaml's niche.topic. They are dealt out to
# the pillars in turn, and the writer turns each into a real title.
EVERGREEN = [
    ("The biggest mistakes people make with {topic}", "The common mistakes, why people make them, what to do instead"),
    ("What I wish I had known when I started with {topic}", "Hard-won lessons from the author's own experience"),
    ("My simple, repeatable system for {topic}", "The steps the author actually uses, and why each one is there"),
    ("A popular belief about {topic} I no longer agree with", "The myth, what real experience showed, the better approach"),
    ("A beginner's guide to {topic} in 5 steps", "The shortest useful path for someone starting today"),
    ("The questions I get asked most about {topic}, answered", "Direct answers to what the audience keeps asking"),
    ("A story from my own journey with {topic}", "One specific moment, what it taught, what changed after"),
    ("Where {topic} is heading, and what I am doing about it", "The author's honest take on a change in the field"),
]

_STOP = {"and", "the", "for", "with", "your", "you", "from", "that", "this", "into", "about", "what", "how"}


def _words(pillar: dict) -> set[str]:
    """Matching words for a pillar: its explicit `keywords`, else the meaningful words of its name and angle."""
    if pillar.get("keywords"):
        return {str(k).lower() for k in pillar["keywords"]}
    text = f"{pillar.get('name', '')} {pillar.get('angle', '')}".lower()
    return {w for w in re.findall(r"[a-z][a-z-]{3,}", text) if w not in _STOP}


def _pillar_for(text: str, pillars: list[dict]) -> str:
    t = text.lower()
    best = max(pillars, key=lambda p: sum(w in t for w in _words(p)))
    return best["key"] if any(w in t for w in _words(best)) else pillars[0]["key"]


def build_calendar(cfg: dict, replace: bool = False) -> list[dict]:
    kb = load_json(KB_PATH)
    if not kb:
        raise SystemExit("No knowledge base yet. Fill in config.yaml, then run `python cli.py ingest`.")
    niche = get_niche(cfg)
    pillars, reader = niche["pillars"], niche["audience"][0]
    existing = [] if replace else (load_json(CALENDAR_PATH, []) or [])
    have = {t["title_idea"].lower() for t in existing}
    topics = list(existing)

    def add(title, angle, pillar, fact_ids, project=None):
        if title.lower() in have:
            return
        have.add(title.lower())
        topics.append({"id": f"T{len(topics) + 1:03d}", "title_idea": title, "angle": angle, "pillar": pillar,
                       "fact_ids": fact_ids, "project": project, "audience": reader,
                       "why_it_matters": "Real experience the reader can learn from and apply.",
                       "status": "planned", "created": dt.date.today().isoformat()})

    # One behind-the-scenes post per featured project (from GitHub or your facts)
    names = cfg.get("ingest", {}).get("display_names", {}) or {}
    for pr in kb.get("projects", []):
        if not pr.get("summary"):
            continue
        display = names.get(pr["name"], pr["name"])
        stem = pr["name"].split("-")[0].split(".")[0].lower()
        fact_ids = [f["id"] for f in kb["facts"] if pr["name"].lower() in f["text"].lower()
                    or display.lower() in f["text"].lower() or (len(stem) > 3 and stem in f["text"].lower())][:6]
        add(f"Behind the scenes: {display} - what I made and what I would do differently", pr.get("summary", "")[:200],
            _pillar_for(pr["name"] + " " + display + " " + pr.get("summary", ""), pillars), fact_ids, project=pr["name"])
    for f in kb.get("facts", []):
        if f.get("kind") == "project" and f.get("source") == "manual":
            add(f"Behind the scenes: {f['text'][:80].rstrip('.')}", f["text"][:200], _pillar_for(f["text"], pillars), [f["id"]])

    # Evergreen shapes, dealt out to the pillars in turn
    for i, (title, angle) in enumerate(EVERGREEN):
        pl = pillars[i % len(pillars)]
        words = _words(pl)
        fact_ids = [f["id"] for f in kb["facts"] if any(w in f["text"].lower() for w in words)][:6]
        add(title.format(topic=niche["topic"] or pl["name"].lower()),
            f"{angle}. Lens: {pl['name']} ({pl['angle']})", pl["key"], fact_ids)

    save_json(CALENDAR_PATH, topics)
    return topics


def expand_with_ai(cfg: dict, n: int = 8) -> list[dict]:
    from .writer import propose_topics
    existing = load_json(CALENDAR_PATH, []) or []
    new = propose_topics(cfg, n, existing)
    have = {t["title_idea"].lower() for t in existing}
    for t in new:
        if t["title_idea"].lower() in have:
            continue
        existing.append({"id": f"T{len(existing) + 1:03d}", **t, "project": None, "status": "planned",
                         "created": dt.date.today().isoformat()})
    save_json(CALENDAR_PATH, existing)
    return existing
