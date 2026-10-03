"""Merge every source into one knowledge base + a human-readable brand brief.

The knowledge base is the ONLY thing the writer is allowed to state facts from.
Every fact gets an id (F001...) so drafts can cite which facts they used.
"""
from __future__ import annotations
import datetime as dt
import re
from ..paths import DATA, FACTS_PATH, KB_PATH, BRIEF_PATH, VOICE_PATH, get_niche, load_json, save_json, write_text


REPLACEMENTS: dict[str, str] = {}
EXCLUDE_LINKS: list[str] = []


def _fact(facts: list, text: str, source: str, kind: str, url: str | None = None):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)
    if url and any(pat in url for pat in EXCLUDE_LINKS):
        url = None
    if len(text) < 12:
        return
    if any(f["text"].lower() == text.lower() for f in facts):
        return
    fid = f"F{len(facts) + 1:03d}"
    entry = {"id": fid, "text": text, "source": source, "kind": kind}
    if url:
        entry["url"] = url
    facts.append(entry)


def build_knowledge_base(cfg: dict) -> dict:
    resume = load_json(DATA / "resume.json")
    linkedin = load_json(DATA / "linkedin.json")
    github = load_json(DATA / "github.json")
    website = load_json(DATA / "website.json")
    voice = VOICE_PATH.read_text(encoding="utf-8").strip() if VOICE_PATH.exists() else ""
    voice = re.sub(r"<!--.*?-->", "", voice, flags=re.S).strip()  # drop the instructions comment
    person = dict(cfg["person"])
    facts: list[dict] = []
    global REPLACEMENTS, EXCLUDE_LINKS
    REPLACEMENTS = dict(cfg.get("ingest", {}).get("text_replacements") or {})
    EXCLUDE_LINKS = list(cfg.get("ingest", {}).get("exclude_link_patterns") or [])

    # --- resume
    if resume:
        for section, items in resume.get("bullets_by_section", {}).items():
            kind = {"Experience": "achievement", "Projects": "project", "Technical Skills": "skill",
                    "Education": "education"}.get(section, "other")
            for b in items:
                _fact(facts, b, "resume", kind)
        header = resume.get("sections", {}).get("Header", "")
        for line in header.splitlines():
            if any(k in line for k in ("Award", "Winner", "Hackathon", "1st", "Top 3", "Featured")):
                for part in re.split(r"\s\|\s", line):
                    kind = "role" if re.search(r"Engineer|Founder|Lead|Developer|CTO", part) else "award"
                    _fact(facts, part, "resume", kind)
        summary = resume.get("sections", {}).get("Summary")
        if summary:
            _fact(facts, summary, "resume", "summary")

    # --- linkedin export
    if linkedin:
        prof = linkedin.get("profile", {})
        if prof.get("headline"):
            person.setdefault("linkedin_headline", prof["headline"])
        if prof.get("summary"):
            _fact(facts, prof["summary"], "linkedin", "summary")
        t = linkedin.get("tables", {})
        for p in t.get("Positions", []):
            span = f"{p.get('Started On', '')} - {p.get('Finished On') or 'Present'}"
            _fact(facts, f"{p.get('Title')} at {p.get('Company Name')} ({span}). {p.get('Description', '')}",
                  "linkedin", "role")
        for e in t.get("Education", []):
            _fact(facts, f"{e.get('Degree Name', '')} at {e.get('School Name')} "
                         f"({e.get('Start Date', '')}-{e.get('End Date', '')}). {e.get('Notes', '')}",
                  "linkedin", "education")
        for h in t.get("Honors", []):
            _fact(facts, f"Honor: {h.get('Title')} ({h.get('Issued On', '')}). {h.get('Description', '')}",
                  "linkedin", "award")
        for c in t.get("Certifications", []):
            _fact(facts, f"Certification: {c.get('Name')} by {c.get('Authority', '')} ({c.get('Started On', '')})",
                  "linkedin", "certification", c.get("Url"))
        for pr in t.get("Projects", []):
            _fact(facts, f"Project: {pr.get('Title')}. {pr.get('Description', '')}", "linkedin", "project", pr.get("Url"))
        for v in t.get("Volunteering", []):
            _fact(facts, f"Volunteering: {v.get('Role')} at {v.get('Company Name')}. {v.get('Description', '')}",
                  "linkedin", "community")
        for r in t.get("Recommendations_Received", []):
            _fact(facts, f"Recommendation from {r.get('First Name', '')} {r.get('Last Name', '')} "
                         f"({r.get('Job Title', '')}, {r.get('Company', '')}): {r.get('Text', '')}",
                  "linkedin", "recommendation")
        skills = [s.get("Name") for s in t.get("Skills", []) if s.get("Name")]
        if skills:
            _fact(facts, "LinkedIn skills: " + ", ".join(skills[:60]), "linkedin", "skill")
        for a in linkedin.get("articles", []):
            _fact(facts, f"Published LinkedIn article: '{a['title']}'. Excerpt: {a['text'][:400]}", "linkedin", "article")
        for post in linkedin.get("posts", [])[:200]:
            if post.get("text") and len(post["text"]) > 80:
                _fact(facts, f"LinkedIn post ({(post.get('date') or '')[:10]}): {post['text'][:500]}",
                      "linkedin", "post", post.get("url"))

    # --- github
    projects = []
    if github:
        gp = github.get("profile", {})
        _fact(facts, f"GitHub: {gp.get('public_repos')} public repos, {gp.get('followers')} followers, "
                     f"account since {str(gp.get('created_at', ''))[:10]}.", "github", "stat", gp.get("html_url"))
        for r in github.get("repos", []):
            if r["name"].lower() == str(github.get("user", "")).lower():
                # Profile README: its bullet points are self-descriptions, not a project.
                for line in (r.get("readme") or "").splitlines():
                    s = line.strip()
                    if s.startswith(("- ", "* ")) and len(s) > 20:
                        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s[2:])     # [text](url) -> text
                        s = re.sub(r"\*\*|__|`", "", s)                         # bold / code marks
                        s = re.sub(r"^[^\w]+", "", s)                           # leading emoji
                        _fact(facts, s, "github-profile", "profile", r["url"])
                continue
            if r.get("featured") or r.get("summary"):
                summary = r.get("summary") or r.get("description") or ""
                r["live_links"] = [l for l in r.get("live_links", []) if not any(p in l for p in EXCLUDE_LINKS)]
                live = ", ".join(r.get("live_links", [])[:2])
                _fact(facts, f"Repo {r['name']} ({r.get('language')}): {summary} {('Live: ' + live) if live else ''}",
                      "github", "project", r["url"])
                projects.append({"name": r["name"], "url": r["url"], "language": r.get("language"),
                                 "summary": summary, "live_links": r.get("live_links", []),
                                 "readme_excerpt": (r.get("readme") or "")[:6000], "pushed_at": r.get("pushed_at")})

    # --- your own facts (data/manual_facts.yaml): credentials, results, stories, milestones
    if FACTS_PATH.exists():
        import yaml
        with open(FACTS_PATH, encoding="utf-8") as fh:
            manual = yaml.safe_load(fh) or {}
        for m in manual.get("facts", []) or []:
            if isinstance(m, dict) and m.get("text"):
                _fact(facts, m["text"], "manual", m.get("kind", "other"), m.get("url"))

    # --- website
    if website:
        for pg in website.get("pages", []):
            if pg.get("ok") and pg.get("description"):
                _fact(facts, f"{pg['title']}: {pg['description']}", "website", "company", pg["url"])

    kb = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "person": person,
        "niche": get_niche(cfg),
        "sources": {"resume": bool(resume), "linkedin_export": bool(linkedin),
                    "github": bool(github), "website": bool(website), "voice_samples": bool(voice)},
        "facts": facts,
        "projects": projects,
        "linkedin_posts": (linkedin or {}).get("posts", [])[:200],
        "linkedin_articles": (linkedin or {}).get("articles", []),
        "resume_text": (resume or {}).get("text", ""),
        "voice_samples": voice,
    }
    save_json(KB_PATH, kb)
    write_text(BRIEF_PATH, render_brief(kb))
    return kb


def render_brief(kb: dict) -> str:
    p, n = kb["person"], kb["niche"]
    lines = [f"# Brand brief - {p['name']}", "",
             f"**Headline:** {p.get('headline', '')}", f"**Niche:** {n['topic']}",
             f"**Location:** {p.get('location', '')}", "",
             "## Angle", (n.get("description") or "").strip(), "",
             "## Links", *[f"- {k}: {v}" for k, v in p.get("links", {}).items() if v], "",
             "## Audience", *[f"- {a}" for a in n["audience"]], "",
             "## Content pillars", *[f"- **{pl['name']}** - {pl['angle']}" for pl in n["pillars"]], "",
             "## Voice", n["voice"], "",
             "## Sources loaded", *[f"- {k}: {'yes' if v else 'no'}" for k, v in kb["sources"].items()], "",
             f"## Facts ({len(kb['facts'])}) - the writer may only assert these"]
    by_kind: dict[str, list] = {}
    for f in kb["facts"]:
        by_kind.setdefault(f["kind"], []).append(f)
    for kind, items in by_kind.items():
        lines.append(f"\n### {kind} ({len(items)})")
        for f in items:
            lines.append(f"- [{f['id']}] ({f['source']}) {f['text']}" + (f" - {f['url']}" if f.get("url") else ""))
    if kb["projects"]:
        lines += ["", "## Featured projects (README excerpts)"]
        for pr in kb["projects"]:
            lines += [f"\n### {pr['name']} - {pr['url']}", pr.get("summary", "")]
            if pr.get("live_links"):
                lines.append("Live: " + ", ".join(pr["live_links"]))
    return "\n".join(lines) + "\n"
