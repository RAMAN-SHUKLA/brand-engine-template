"""Media kit: a one-page summary for brands, podcasts, event organisers and collaborators.
Built only from config.yaml and knowledge-base facts, so nothing in it is invented."""
from __future__ import annotations
import datetime as dt
import html
import markdown
from ..paths import OUTREACH, KB_PATH, load_json, write_text

DEFAULT_OFFERS = ["Sponsored posts and brand collaborations", "Guest appearances (podcasts, live sessions, events)",
                  "Workshops and talks", "Content partnerships and co-created posts"]


def _facts(kb: dict, kinds: tuple[str, ...]) -> list[dict]:
    return [f for f in kb["facts"] if f["kind"] in kinds and "[FILL" not in f["text"]]


def build_media_kit(cfg: dict) -> dict:
    kb = load_json(KB_PATH)
    if not kb:
        raise SystemExit("No knowledge base yet. Fill in config.yaml, then run `python cli.py ingest`.")
    p, n = kb["person"], kb["niche"]
    based = f" from {p['location']}" if p.get("location") else ""
    bio = f"{p['name']} creates content about {n['topic']}{based}."
    offers = (cfg.get("media_kit") or {}).get("offers") or DEFAULT_OFFERS
    links = {k: v for k, v in p.get("links", {}).items() if v}

    md = [f"# {p['name']} — media kit", "", f"**{p.get('headline', '')}**", "",
          " | ".join(x for x in (p.get("location", ""), p.get("email", "")) if x), "",
          " | ".join(f"[{k}]({v})" for k, v in links.items()), "",
          "## About", bio, "", " ".join(str(n.get("description") or "").split()), "",
          "## What I create"] + [f"- **{pl['name']}**: {pl['angle']}" for pl in n["pillars"]] + [
          "", "## Who it reaches"] + [f"- {a}" for a in n["audience"]] + [""]
    highlights = _facts(kb, ("award", "achievement", "speaking", "judging", "mentoring", "stat", "role"))
    if highlights:
        md += ["## Highlights"] + [f"- {f['text']}" + (f" ([link]({f['url']}))" if f.get("url") else "")
                                   for f in highlights[:10]] + [""]
    projects = _facts(kb, ("project",))
    if projects:
        md += ["## Selected work"] + [f"- {f['text']}" for f in projects[:6]] + [""]
    md += ["## Ways to work together"] + [f"- {o}" for o in offers] + ["",
           f"*Generated {dt.date.today().isoformat()} from verified facts.*"]
    text = "\n".join(md) + "\n"
    write_text(OUTREACH / "media_kit.md", text)
    body = markdown.markdown(text, extensions=["tables"])
    page = ("<!doctype html><html><head><meta charset='utf-8'><title>" + html.escape(f"{p['name']} media kit") +
            "</title><style>body{max-width:760px;margin:40px auto;font:16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;"
            "color:#1a1a1a;padding:0 16px}h1{font-size:30px}h2{margin-top:1.8em;border-bottom:1px solid #ddd;padding-bottom:4px}"
            "em{color:#555}a{color:#0a58ca}</style></head><body>" + body + "</body></html>")
    write_text(OUTREACH / "media_kit.html", page)
    return {"markdown": str(OUTREACH / "media_kit.md"), "html": str(OUTREACH / "media_kit.html")}
