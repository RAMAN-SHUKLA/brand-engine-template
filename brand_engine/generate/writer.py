"""Grounded writer: turns a topic + knowledge base into platform-ready drafts via the Claude API.

Every draft is saved under drafts/<slug>/ with a meta.json that records which knowledge-base
facts were used, which claims the model itself flagged, and which numbers the post-check could
not find in the knowledge base. Nothing here publishes anything.
"""
from __future__ import annotations
import datetime as dt
import json
import re
from pathlib import Path

from ..paths import DRAFTS, KB_PATH, BRIEF_PATH, get_niche, load_json, read_text, save_json, write_text
from ..util import slugify, join_frontmatter, numbers_in
from .prompts import (BATCH_SCHEMA, POST_SCHEMA, TOPIC_SCHEMA, batch_user, shorts_system, stable_context,
                      topics_user, writer_system, writer_user)


def _client():
    import anthropic  # imported lazily so ingest/publish work without the SDK
    return anthropic.Anthropic()


def call_json(system_blocks: list[dict], user: str, schema: dict, wcfg: dict) -> tuple[dict, dict]:
    """One structured-output call. Streams (long output) and returns (parsed_json, usage_dict)."""
    client = _client()
    kwargs = dict(
        model=wcfg.get("model", "claude-opus-5-5"),
        max_tokens=int(wcfg.get("max_tokens", 64000)),
        system=system_blocks,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": wcfg.get("effort", "high"),
                       "format": {"type": "json_schema", "schema": schema}},
    )
    msg = None
    if wcfg.get("use_refusal_fallbacks", True):
        try:
            with client.beta.messages.stream(**kwargs, betas=["server-side-fallback-2026-07-01"],
                                             fallbacks="default") as stream:
                msg = stream.get_final_message()
        except TypeError:
            msg = None  # SDK too old for `fallbacks`; fall through to the plain call
    if msg is None:
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()

    if msg.stop_reason == "refusal":
        details = getattr(msg, "stop_details", None)
        raise RuntimeError(f"Model declined the request: {details}")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Output hit max_tokens before finishing; raise writer.max_tokens in config.yaml")
    text = next(b.text for b in msg.content if b.type == "text")
    usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens,
             "cache_read_input_tokens": getattr(msg.usage, "cache_read_input_tokens", None),
             "cache_creation_input_tokens": getattr(msg.usage, "cache_creation_input_tokens", None),
             "model": msg.model}
    return json.loads(text), usage


def _system_blocks(kb: dict, cfg: dict, rules: str | None = None) -> list[dict]:
    brief = read_text(BRIEF_PATH) if BRIEF_PATH.exists() else ""
    return [
        # Stable across every post -> cached. Rules go after it so tweaking them keeps the cache.
        {"type": "text", "text": stable_context(kb, brief), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": rules or writer_system(cfg)},
    ]


def _load_kb() -> dict:
    kb = load_json(KB_PATH)
    if not kb:
        raise SystemExit("No knowledge base yet. Fill in config.yaml, then run `python cli.py ingest`.")
    return kb


def _grounding_text(kb: dict, topic: dict) -> str:
    parts = [f["text"] for f in kb.get("facts", [])]
    parts += [pr.get("readme_excerpt", "") + " " + pr.get("summary", "") for pr in kb.get("projects", [])]
    parts += [p.get("text", "") for p in kb.get("linkedin_posts", [])]
    parts.append(json.dumps(topic, ensure_ascii=False))
    parts.append(kb.get("resume_text", ""))
    parts.append(kb.get("voice_samples", ""))
    return "\n".join(parts)


def post_checks(draft: dict, kb: dict, topic: dict, cfg: dict) -> list[str]:
    warnings: list[str] = []
    known = {f["id"] for f in kb.get("facts", [])}
    bad_ids = [fid for fid in draft.get("facts_used", []) if fid not in known]
    if bad_ids:
        warnings.append(f"facts_used contains unknown ids: {bad_ids}")
    if not draft.get("facts_used"):
        warnings.append("facts_used is empty - the post may not be grounded")

    body = draft.get("body_markdown", "")
    code_free = re.sub(r"```.*?```", "", body, flags=re.S)
    grounded_numbers = numbers_in(_grounding_text(kb, topic))
    stray = sorted(n for n in numbers_in(code_free) if n not in grounded_numbers)
    if stray:
        warnings.append(f"numbers in the post not found anywhere in the knowledge base: {stray}")

    fills = re.findall(r"\[FILL:[^\]]*\]", body + draft.get("linkedin_post", ""))
    if fills:
        warnings.append(f"{len(fills)} [FILL] placeholder(s) need your input before publishing")

    lower = body.lower()
    for phrase in get_niche(cfg)["banned_phrases"]:
        if phrase.lower() in lower:
            warnings.append(f"banned phrase present: '{phrase}'")

    if len(draft.get("linkedin_post", "")) > 3000:
        warnings.append("linkedin_post exceeds 3000 characters")
    for i, t in enumerate(draft.get("x_thread", []), 1):
        if len(t) > 280:
            warnings.append(f"x_thread post {i} exceeds 280 characters")
    tags = draft.get("tags", [])
    if "devto" in cfg["publish"].get("platforms", []) and len(tags) != 4 or any(not re.fullmatch(r"[a-z0-9]+", t) for t in tags):
        warnings.append(f"tags must be exactly 4 lowercase alphanumerics; got {tags}")
    return warnings


def save_draft(draft: dict, topic: dict, warnings: list[str], usage: dict, cfg: dict) -> Path:
    slug = slugify(draft.get("slug") or draft["title"])
    folder = DRAFTS / slug
    i = 2
    while folder.exists() and (folder / "post.md").exists():
        folder = DRAFTS / f"{slug}-{i}"
        i += 1
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "title": draft["title"], "subtitle": draft.get("subtitle", ""), "slug": folder.name,
        "tags": draft.get("tags", []), "pillar": topic.get("pillar"),
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "status": "draft", "canonical_url": None, "cover_image_prompt": draft.get("cover_image_prompt", ""),
    }
    write_text(folder / "post.md", join_frontmatter(meta, draft["body_markdown"]))
    write_text(folder / "linkedin.txt", draft.get("linkedin_post", ""))
    write_text(folder / "x_thread.txt", "\n\n---\n\n".join(
        f"{i}/ {t}" for i, t in enumerate(draft.get("x_thread", []), 1)))
    save_json(folder / "meta.json", {
        "topic": topic, "facts_used": draft.get("facts_used", []),
        "claims_to_verify": draft.get("claims_to_verify", []), "warnings": warnings,
        "usage": usage, "model": cfg["writer"].get("model"),
    })
    return folder


def write_post(topic: dict, cfg: dict) -> Path:
    kb = _load_kb()
    draft, usage = call_json(_system_blocks(kb, cfg), writer_user(topic), POST_SCHEMA, cfg["writer"])
    warnings = post_checks(draft, kb, topic, cfg)
    folder = save_draft(draft, topic, warnings, usage, cfg)
    return folder


def propose_topics(cfg: dict, n: int, existing: list[dict]) -> list[dict]:
    kb = _load_kb()
    data, _ = call_json(_system_blocks(kb, cfg), topics_user(kb, cfg, n, existing), TOPIC_SCHEMA, cfg["writer"])
    return data["topics"]


def generate_batch(cfg: dict, week: str, n: int = 7, platform: str = "linkedin", notes: str = "",
                   append: bool = False) -> Path:
    """Write `n` short posts for `platform` into data/batches/<week>/ (status draft), grounded in the
    knowledge base and the niche in config.yaml. Review, then `batch approve` and `batch schedule`."""
    from . import shorts
    kb = _load_kb()
    existing = load_json(shorts.BATCHES / week / "posts.json")
    if existing and not append:
        raise SystemExit(f"Batch {week} already exists. Add --append to add more posts to it, or pick another --week.")
    sig = ((cfg["publish"].get(platform) or {}).get("signature") or "").strip()
    budget = shorts.LIMITS.get(platform, 3000) - (len(sig) + 2 if sig else 0) - 10
    if platform == "linkedin":
        budget = min(budget, 1300)  # long enough for substance, short enough to read on a phone
    recent = [p["text"] for b in shorts.list_batches() for p in shorts.load_batch(b)["posts"]]
    data, usage = call_json(_system_blocks(kb, cfg, shorts_system(cfg)),
                            batch_user(cfg, n, platform, budget, notes, recent), BATCH_SCHEMA, cfg["writer"])
    grounded = numbers_in(_grounding_text(kb, {"notes": notes}))
    posts = []
    for p in data["posts"][:n]:
        stray = sorted(x for x in numbers_in(p["text"]) if x not in grounded)
        if stray:
            p["claims_to_verify"] = p.get("claims_to_verify", []) + [f"numbers not found in your facts: {stray}"]
        posts.append({**p, "platforms": [platform], "kind": "evergreen", "status": "draft"})
    print(f"model: {usage['model']} | tokens in/out: {usage['input_tokens']}/{usage['output_tokens']}"
          f" | cache read: {usage.get('cache_read_input_tokens')}")
    if existing:
        for i, p in enumerate(posts, len(existing["posts"]) + 1):
            p["id"] = f"P{i:02d}"
        existing["posts"] += posts
        return shorts.save_batch(existing, cfg)
    return shorts.new_batch(week, [], posts, cfg)
