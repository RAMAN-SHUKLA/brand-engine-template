from __future__ import annotations
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MEDIA = DATA / "media"
DRAFTS = ROOT / "drafts"
OUTREACH = ROOT / "outreach_out"
for _p in (DATA, MEDIA, DRAFTS, OUTREACH):
    _p.mkdir(parents=True, exist_ok=True)

KB_PATH = DATA / "knowledge_base.json"
BRIEF_PATH = DATA / "brand_brief.md"
CALENDAR_PATH = DATA / "content_calendar.json"
PUBLISH_LOG = DATA / "publish_log.json"
FACTS_PATH = DATA / "manual_facts.yaml"
VOICE_PATH = DATA / "voice_samples.md"


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_niche(cfg: dict) -> dict:
    """config.yaml's `niche` block, with safe defaults for every field the writer reads."""
    n = dict(cfg.get("niche") or {})
    n.setdefault("topic", "")
    n.setdefault("description", "")
    n["audience"] = n.get("audience") or ["people interested in this topic"]
    if isinstance(n["audience"], str):
        n["audience"] = [n["audience"]]
    n["pillars"] = n.get("pillars") or [{"key": "general", "name": "General", "angle": "Useful, honest posts"}]
    for k in ("keywords", "hashtags", "content_rules", "avoid_mentions", "banned_phrases"):
        n[k] = n.get(k) or []
    n["voice"] = (n.get("voice") or "Clear, direct, first-person.").strip()
    n.setdefault("goal", "")
    n.setdefault("call_to_action", "")
    return n


def load_json(path: Path, default=None):
    if not Path(path).exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def read_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")
