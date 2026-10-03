"""Prompts and output schemas for the grounded writer.

Nothing here is specific to one niche: who the author is, what they post about, who they talk to and
how they sound all come from config.yaml (`person` and `niche`) and the knowledge base.
"""
from __future__ import annotations
import json

from ..paths import get_niche

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Specific, concrete, no clickbait. <= 70 chars."},
        "subtitle": {"type": "string", "description": "One sentence, the promise of the piece."},
        "slug": {"type": "string", "description": "kebab-case url slug"},
        "tags": {"type": "array", "items": {"type": "string"},
                 "description": "Exactly 4 tags, lowercase, letters and digits only (Dev.to rules), e.g. fitness, habits, beginners, nutrition"},
        "body_markdown": {"type": "string", "description": "The full long-form post in Markdown. No H1 (title is separate). Start at the hook."},
        "linkedin_post": {"type": "string"},
        "x_thread": {"type": "array", "items": {"type": "string"}},
        "facts_used": {"type": "array", "items": {"type": "string"},
                       "description": "Fact ids (F001...) from the knowledge base that the post relies on."},
        "claims_to_verify": {"type": "array", "items": {"type": "string"},
                             "description": "Any statement you were not 100% able to ground in the knowledge base."},
        "cover_image_prompt": {"type": "string", "description": "A one-line idea for a cover image or photo that suits the post."},
    },
    "required": ["title", "subtitle", "slug", "tags", "body_markdown", "linkedin_post", "x_thread",
                 "facts_used", "claims_to_verify", "cover_image_prompt"],
    "additionalProperties": False,
}

TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title_idea": {"type": "string"},
                    "angle": {"type": "string", "description": "What is the specific, non-obvious point? 1-2 sentences."},
                    "pillar": {"type": "string", "description": "The `key` of one of the author's content pillars."},
                    "fact_ids": {"type": "array", "items": {"type": "string"}},
                    "audience": {"type": "string"},
                    "why_it_matters": {"type": "string", "description": "Why this reader would stop scrolling for it."},
                },
                "required": ["title_idea", "angle", "pillar", "fact_ids", "audience", "why_it_matters"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["topics"],
    "additionalProperties": False,
}

BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pillar": {"type": "string", "description": "The `key` of the content pillar this post belongs to."},
                    "text": {"type": "string", "description": "The complete post as plain text, ready to publish."},
                    "facts_used": {"type": "array", "items": {"type": "string"},
                                   "description": "Fact ids (F001...) the post relies on; empty if it relies on none."},
                    "claims_to_verify": {"type": "array", "items": {"type": "string"}},
                    "image_idea": {"type": "string", "description": "One line: a photo or graphic that would suit this post."},
                },
                "required": ["pillar", "text", "facts_used", "claims_to_verify", "image_idea"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["posts"],
    "additionalProperties": False,
}

# Hashtag guidance per short-post platform.
HASHTAG_RULES = {
    "linkedin": "End with one line of 3-5 hashtags, mixing broad and niche ones.",
    "threads": "Use at most one hashtag (Threads turns the first one into a topic tag), or none.",
    "bluesky": "Use at most two hashtags, or none.",
}


def stable_context(kb: dict, brief_md: str) -> str:
    """Everything that is the same for every post. Goes in the cached system block."""
    projects = []
    for pr in kb.get("projects", []):
        projects.append(f"### {pr['name']} ({pr.get('language')}) - {pr['url']}\n"
                        f"{pr.get('summary', '')}\n"
                        + (("Live: " + ", ".join(pr['live_links']) + "\n") if pr.get("live_links") else "")
                        + (f"README excerpt:\n{pr['readme_excerpt']}\n" if pr.get("readme_excerpt") else ""))
    recent_posts = "\n".join(
        f"- ({(p.get('date') or '')[:10]}) {(p.get('text') or '')[:300]}"
        for p in kb.get("linkedin_posts", [])[:40] if p.get("text")
    )
    voice = (kb.get("voice_samples") or "").strip()
    return (
        "# KNOWLEDGE BASE (the only source of truth about the author)\n\n"
        + brief_md
        + ("\n\n# FEATURED PROJECT DETAILS\n\n" + "\n".join(projects) if projects else "")
        + ("\n\n# THE AUTHOR'S OWN PAST POSTS (match this voice and rhythm; facts in them may be reused)\n\n" + voice
           if voice else "")
        + ("\n\n# AUTHOR'S OWN RECENT LINKEDIN POSTS (voice reference; may be reused)\n" + recent_posts if recent_posts else "")
    )


def _niche_block(cfg: dict) -> str:
    p, n = cfg.get("person", {}), get_niche(cfg)
    pillars = "\n".join(f"  - {pl['key']}: {pl['name']} -- {pl['angle']}" for pl in n["pillars"])
    lines = [
        f"AUTHOR: {p.get('name', 'the author')}" + (f" -- {p['headline']}" if p.get("headline") else ""),
        f"NICHE: {n['topic'] or '(see knowledge base)'}",
        f"ANGLE: {' '.join(str(n['description']).split()) or '(see knowledge base)'}",
        "AUDIENCE: " + "; ".join(n["audience"]),
    ]
    if n["goal"]:
        lines.append(f"GOAL OF THE CONTENT: {n['goal']}")
    lines += [f"CONTENT PILLARS:\n{pillars}", f"VOICE: {n['voice']}"]
    if n["keywords"]:
        lines.append("SEARCH KEYWORDS THE AUDIENCE USES: " + ", ".join(n["keywords"]))
    if n["hashtags"]:
        lines.append("HASHTAG POOL (rotate; pick the most relevant): " + " ".join(n["hashtags"]))
    if n["content_rules"]:
        lines.append("AUTHOR'S OWN RULES (always follow):\n" + "\n".join(f"  - {r}" for r in n["content_rules"]))
    return "\n".join(lines)


def _shared_rules(cfg: dict) -> str:
    n = get_niche(cfg)
    banned = ", ".join(f'"{b}"' for b in n["banned_phrases"]) or "(none)"
    cta = (f'When a call to action fits, use this one, in your own words: "{n["call_to_action"]}". '
           "Never more than one call to action per post."
           if n["call_to_action"] else
           "Close with one genuine question that invites the reader to share their own experience.")
    return f"""GOAL & POSITIONING (SUBTLE, NOT STATED)
Authority comes from demonstrated knowledge, real experience and teaching clarity, never from stated intent.
- Be genuinely useful to the audience first. Every post must leave the reader with something they can use or think about.
- No hard selling, no begging for engagement ("like and share!"), no announcing that you are "building a personal brand".

DISCOVERABILITY
1. Hook: the first 1-2 lines (under 200 characters) must stop the scroll on their own: concrete, specific, curiosity or tension.
2. Keywords: weave the audience's search terms in naturally where they fit. Never keyword-stuff.
3. Searchable framing: answer questions the audience actually asks ("How do I...", "Why does...", "What should I know about...").
4. Consistency: stay inside the author's niche and pillars so the audience knows what to expect.

HARD RULES (violating these is a failure)
1. Only assert facts about the author that appear in the knowledge base (facts F001..., their own past posts, project details).
   Never invent numbers, results, clients, testimonials, credentials, prices, dates, quotes, statistics or studies.
2. If a concrete detail would strengthen the piece but is NOT in the knowledge base, write the placeholder
   [FILL: <exactly what the author should insert>] instead of guessing. Placeholders are good; fabrication is not.
3. General advice is fine, but present it as the author's experience or opinion, not as an unsourced statistic.
4. Voice: write exactly as described under VOICE, in the first person, as the author.
5. Never use these phrases: {banned}.
6. Never mention: {', '.join(n['avoid_mentions']) or '(none)'}.
7. Do not exaggerate the author's experience, seniority or results. Lean on what they have actually done.
8. Facts of kind "company" are marketing copy from websites. They are context, never personal achievements.
9. Include code, recipes, scripts, templates or worked examples only when they suit the niche and the topic.

CALL TO ACTION
{cta}"""


def writer_system(cfg: dict) -> str:
    target = cfg.get("writer", {}).get("target_words", 1200)
    reader = get_niche(cfg)["audience"][0]
    return f"""You are the ghostwriter for a content creator, writing in the first person as them.

{_niche_block(cfg)}

{_shared_rules(cfg)}

LONG-FORM STRUCTURE (body_markdown, ~{target} words)
- Open on a concrete moment, problem or wrong assumption your reader ({reader}) recognises. No throat-clearing.
- The context: what happened or what the reader is up against, with real constraints.
- The substance: 3-5 specific points, steps or lessons, each with the reason it works or matters.
- What went wrong, the common mistake, or what you would do differently.
- A short "If you are {reader}" section with 3-5 direct, actionable takeaways.
- Close per CALL TO ACTION. Use H2/H3 headings, short paragraphs, occasional lists.
- Use links from the knowledge base inline where natural.

PLATFORM VARIANTS
- linkedin_post: <= 2,800 characters, plain text (no markdown, no bold).
  - First 1-2 lines: standalone hook under 200 characters.
  - 4-7 short paragraphs with clean line breaks.
  - Close per CALL TO ACTION. Where the long-form link goes, write [LINK].
  - Final line: 3-5 topic-specific hashtags.
- x_thread: 5-8 posts, each <= 270 characters, numbered "1/" style prefix NOT included (client adds it).
  First post is a self-contained hook. Last post contains [LINK].
- tags: exactly 4, lowercase letters/digits only.

OUTPUT
Return only the JSON object matching the provided schema."""


def shorts_system(cfg: dict) -> str:
    return f"""You are the ghostwriter for a content creator, writing short social posts in the first person as them.

{_niche_block(cfg)}

{_shared_rules(cfg)}

SHORT-POST CRAFT
- One idea per post. Cut everything that does not serve it.
- Plain text only: no markdown, no bold, no headings. Short lines and white space for readability on a phone.
- Vary the format across a batch: a quick tip, a story, a myth vs fact, a list, a contrarian opinion, a question.
- Spread posts across the content pillars; do not repeat a hook pattern or an opening word within a batch.
- Each post must make sense on its own, without the others.

OUTPUT
Return only the JSON object matching the provided schema."""


def writer_user(topic: dict) -> str:
    return (
        "Write the post described below.\n\n"
        f"TOPIC: {topic.get('title_idea')}\n"
        f"ANGLE: {topic.get('angle', '')}\n"
        f"PILLAR: {topic.get('pillar', '')}\n"
        f"PRIMARY READER: {topic.get('audience') or 'the main audience described above'}\n"
        + (f"WHY IT MATTERS TO THEM: {topic['why_it_matters']}\n" if topic.get("why_it_matters") else "")
        + f"SUGGESTED FACT IDS: {', '.join(topic.get('fact_ids', [])) or 'choose the most relevant'}\n"
        + (f"PROJECT FOCUS: {topic['project']}\n" if topic.get("project") else "")
        + (f"EXTRA NOTES FROM AUTHOR: {topic['notes']}\n" if topic.get("notes") else "")
    )


def topics_user(kb: dict, cfg: dict, n: int, existing: list[dict]) -> str:
    niche = get_niche(cfg)
    pillars = "\n".join(f"- {p['key']}: {p['name']} ({p['angle']})" for p in niche["pillars"])
    have = "\n".join(f"- {t['title_idea']}" for t in existing) or "(none yet)"
    return (
        f"Propose {n} new post topics for the author, grounded in the knowledge base and the author's niche.\n"
        f"Each must make a specific, non-obvious point that {niche['audience'][0]} would find valuable,\n"
        f"and should draw on the author's real experience where possible (cite fact ids). Spread across these pillars:\n{pillars}\n\n"
        f"Avoid duplicating these existing topics:\n{have}\n\n"
        "Return JSON matching the schema."
    )


def batch_user(cfg: dict, n: int, platform: str, char_budget: int, notes: str = "",
               avoid: list[str] | None = None) -> str:
    niche = get_niche(cfg)
    pillars = ", ".join(p["key"] for p in niche["pillars"])
    recent = "\n".join(f"- {t[:160]}" for t in (avoid or [])[-40:]) or "(none)"
    return (
        f"Write {n} short {platform} posts for the author's week.\n\n"
        f"PLATFORM: {platform}\n"
        f"LENGTH: each post at most {char_budget} characters including hashtags "
        f"(a signature is appended automatically; do not add one).\n"
        f"HASHTAGS: {HASHTAG_RULES.get(platform, 'Use at most two hashtags.')}\n"
        f"PILLARS TO SPREAD ACROSS: {pillars}\n"
        + (f"WHAT IS HAPPENING THIS WEEK / NOTES FROM THE AUTHOR:\n{notes}\n" if notes else "")
        + f"\nDo not repeat these recent posts (topics or hooks):\n{recent}\n\n"
        f"Return exactly {n} posts as JSON matching the schema."
    )


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
