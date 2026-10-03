"""Post queue: approved content + scheduled times + a runner that a scheduler calls twice an hour.

Queue items:
  * long-form drafts   -> {"slug": "<drafts folder>", "platforms": ["devto", "linkedin", ...]}
  * short batch posts  -> {"batch": "2026-W36", "post_id": "P07", "platforms": ["linkedin"] or ["bluesky"] ...}

Adapters: linkedin (Posts API), bluesky (AT Protocol), devto/hashnode/medium via publisher.run for long-form.
LinkedIn's API has no native scheduling, Bluesky has none either, so the schedule lives here and GitHub Actions
(.github/workflows/post-queue.yml) runs `queue run` on a cron.

Safety rails:
  * only approved content can be queued
  * items overdue by more than `max_late_hours` are skipped, not dumped all at once
  * one queue item per run (an item may fan out to several platforms)
"""
from __future__ import annotations
import datetime as dt
import os
import re
import time

from ..paths import DATA, ROOT, PUBLISH_LOG, load_config, load_json, save_json, write_text
from ..util import join_frontmatter
from .publisher import load_draft, _blockers
from . import linkedin

QUEUE_PATH = DATA / "post_queue.json"
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
QUEUEABLE = ("approved", "drafted", "published")
CHAR_LIMITS = {"linkedin": 3000, "bluesky": 300, "threads": 500}


def _now() -> dt.datetime:
    return dt.datetime.now().replace(second=0, microsecond=0)


def parse_when(s: str) -> dt.datetime:
    s = s.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise SystemExit(f"Cannot parse time '{s}'. Use YYYY-MM-DD HH:MM (24h, local time).")


def load_queue() -> list[dict]:
    return load_json(QUEUE_PATH, []) or []


def _label(item: dict) -> str:
    base = item.get("slug") or f"{item.get('batch')}/{item.get('post_id')}"
    return f"{base} -> {','.join(item.get('platforms', []))}"


# ----------------------------------------------------------------------------- approve / add

def approve(slug: str, ignore_warnings: bool = False) -> dict:
    d = load_draft(slug)
    blockers = _blockers(d)
    if blockers and not ignore_warnings:
        raise SystemExit("Cannot approve, fix these first (or pass --ignore-warnings):\n  - " + "\n  - ".join(blockers))
    if d["meta"].get("status") in ("draft", None):
        d["meta"]["status"] = "approved"
    d["meta"]["approved_at"] = _now().isoformat(timespec="minutes")
    write_text(d["folder"] / "post.md", join_frontmatter(d["meta"], d["body"]))
    return d["meta"]


def _new_item(when: dt.datetime, q: list[dict], platforms, **fields) -> dict:
    if when < _now():
        raise SystemExit(f"{when} is in the past.")
    nums = [int(m.group(1)) for i in q for m in [re.match(r"Q(\d+)$", i.get("id", ""))] if m]
    return {"id": f"Q{(max(nums) + 1 if nums else 1):03d}", **fields, "platforms": list(platforms),
            "scheduled_at": when.isoformat(timespec="minutes"), "status": "queued",
            "created": _now().isoformat(timespec="minutes"), "results": []}


def add(slug: str, when: dt.datetime, platforms: tuple[str, ...] = ("linkedin",)) -> dict:
    d = load_draft(slug)
    if d["meta"].get("status") not in QUEUEABLE:
        raise SystemExit(f"Draft '{slug}' has status '{d['meta'].get('status')}'. "
                         f"Run `python cli.py approve --slug {slug}` first.")
    q = load_queue()
    if any(i.get("slug") == slug and i["status"] == "queued" and set(i["platforms"]) & set(platforms) for i in q):
        raise SystemExit(f"'{slug}' is already queued for one of {platforms}. Remove it first to reschedule.")
    item = _new_item(when, q, platforms, slug=slug)
    q.append(item)
    save_json(QUEUE_PATH, q)
    return item


def add_short(batch: str, post_id: str, when: dt.datetime, platforms: tuple[str, ...] = ("linkedin",),
              allow_repeat: bool = False) -> dict:
    """Queue one approved post from a weekly batch (see generate/shorts.py).
    allow_repeat lets evergreen posts be scheduled again later (recycling)."""
    q = load_queue()
    if not allow_repeat and any(i.get("batch") == batch and i.get("post_id") == post_id and i["status"] == "queued" for i in q):
        raise SystemExit(f"{batch}/{post_id} is already queued.")
    item = _new_item(when, q, platforms, batch=batch, post_id=post_id)
    q.append(item)
    save_json(QUEUE_PATH, q)
    return item


def remove(item_id: str) -> bool:
    q = load_queue()
    new = [i for i in q if not (i["id"] == item_id and i["status"] == "queued")]
    save_json(QUEUE_PATH, new)
    return len(new) != len(q)


# ----------------------------------------------------------------------------- slots

def next_slots(days: list[str], times: list[str] | str, start: dt.datetime | None, count: int,
               busy: set[str] | None = None) -> list[dt.datetime]:
    """Upcoming free (weekday, time) slots, e.g. days=['mon',...,'sun'], times=['09:00','18:00']."""
    if isinstance(times, str):
        times = times.split(",")
    wanted = {WEEKDAYS[d.strip().lower()[:3]] for d in days}
    hhmm = sorted((int(t.split(":")[0]), int(t.split(":")[1])) for t in times if t.strip())
    busy = busy or set()
    day = (start or _now()).replace(hour=0, minute=0)
    out: list[dt.datetime] = []
    guard = 0
    while len(out) < count and guard < 3660:
        guard += 1
        if day.weekday() in wanted:
            for hh, mm in hhmm:
                slot = day.replace(hour=hh, minute=mm)
                if slot > _now() and slot.isoformat(timespec="minutes") not in busy:
                    out.append(slot)
                    if len(out) == count:
                        break
        day += dt.timedelta(days=1)
    return out


def busy_slots(platform: str | None = None) -> set[str]:
    return {i["scheduled_at"] for i in load_queue()
            if i["status"] == "queued" and (platform is None or platform in i.get("platforms", []))}


def auto_plan(days: list[str], times: list[str] | str, start: dt.datetime | None = None,
              platforms: tuple[str, ...] = ("linkedin",)) -> list[dict]:
    """Queue every approved-but-unqueued long-form draft into the next free slots."""
    from ..paths import DRAFTS
    from ..util import split_frontmatter
    q = load_queue()
    queued_slugs = {i.get("slug") for i in q if i["status"] in ("queued", "posted")}
    candidates = []
    for folder in sorted(DRAFTS.iterdir()):
        post = folder / "post.md"
        if post.exists() and folder.name not in queued_slugs:
            meta, _ = split_frontmatter(post.read_text(encoding="utf-8"))
            if meta.get("status") in QUEUEABLE:
                candidates.append(folder.name)
    if not candidates:
        return []
    slots = next_slots(days, times, start, len(candidates), busy_slots(platforms[0]))
    return [add(slug, when, platforms) for slug, when in zip(candidates, slots)]


# ----------------------------------------------------------------------------- text per platform

def with_signature(text: str, cfg: dict, platform: str = "linkedin") -> str:
    """Append the platform's signature; keep a trailing hashtag line last; never exceed the platform limit."""
    sig = (cfg["publish"].get(platform, {}).get("signature") or "").strip()
    text = text.strip()
    if not sig or sig in text:
        return text
    # Guard: if the text already contains social profile links, skip appending
    # the signature to prevent duplicate links when a post embeds its own footer.
    _social_anchor = (cfg.get("person", {}).get("links", {}).get("linkedin") or "").split("://")[-1].rstrip("/")
    if _social_anchor and _social_anchor in text:
        return text
    limit = CHAR_LIMITS.get(platform, 3000)
    if len(text) + len(sig) + 2 > limit:
        return text
    lines = text.split("\n")
    last = lines[-1].strip()
    if last and all(tok.startswith("#") for tok in last.split()):
        return "\n".join(lines[:-1]).rstrip() + "\n\n" + sig + "\n\n" + last
    return text + "\n\n" + sig


def text_for(platform: str, post: dict, cfg: dict) -> str:
    text = (post.get("variants") or {}).get(platform) or post["text"]
    if platform == "linkedin":
        text = text.replace("[LINK]", post.get("link") or "")
    return with_signature(text, cfg, platform)


def _media_paths(post: dict) -> list[str]:
    """Local files for a post's images; http(s) URLs (share cards) are downloaded to a temp cache."""
    from .media import resolve_media
    return resolve_media(post.get("images") or [])


def _default_alt() -> str:
    try:
        cfg = load_config()
        person = cfg.get("person", {})
        name = person.get("name", "")
        headline = person.get("headline", "")
        parts = [p for p in [name, headline] if p]
        return " — ".join(parts) or "Author"
    except Exception:
        return "Author"


def _linkedin_card(post: dict) -> tuple[str | None, str | None]:
    """The post's first usable image (local path, or URL downloaded to a temp file) for a LinkedIn image post.
    Returns (local_path, alt), or (None, None) when the post has no usable image (it then goes out as text)."""
    import os
    from .media import resolve_media
    candidates = list(post.get("images") or [])
    alts = list(post.get("image_alts") or [])
    for i, c in enumerate(candidates):
        try:
            path = resolve_media([c])[0]
            if not os.path.exists(path):
                raise FileNotFoundError(path)
            alt = alts[i] if i < len(alts) else _default_alt()
            return path, alt
        except Exception as e:  # noqa: BLE001 — try the next image
            print(f"  [linkedin] image unavailable ({str(e)[:80]}), trying next")
    return None, None


def _threads_media_url(post: dict) -> tuple[str, str]:
    """Threads takes a public image URL directly (no upload, unlike Bluesky/LinkedIn): the post's own image
    if it is an http(s) URL, else "" (the post goes out as text)."""
    imgs = post.get("images") or []
    if imgs and str(imgs[0]).startswith(("http://", "https://")):
        alt = (post.get("image_alts") or [None])[0] or _default_alt()
        return imgs[0], alt
    return "", _default_alt()


# ----------------------------------------------------------------------------- publish one item

def _publish_short(item: dict, cfg: dict, dry_run: bool) -> list[dict]:
    from ..generate import shorts
    batch = shorts.load_batch(item["batch"])
    post = next((p for p in batch["posts"] if p["id"] == item["post_id"]), None)
    if not post:
        raise RuntimeError(f"{item['batch']}/{item['post_id']} not found")
    if post.get("status") not in ("approved", "queued", "posted"):
        raise RuntimeError(f"{item['batch']}/{item['post_id']} is '{post.get('status')}', not approved")
    results = []
    for platform in item["platforms"]:
        # Duplicate protection: skip if post already has a live URL for this platform (in batch or publish_log)
        already_url = post.get("posted_urls", {}).get(platform)
        if not already_url and not dry_run:
            pub_log = load_json(PUBLISH_LOG, []) or []
            existing_entry = next((l for l in pub_log if l.get("item") == f"{item['batch']}/{item['post_id']} -> {platform}"
                                  and any(r.get("platform") == platform and (r.get("url") or r.get("id")) for r in l.get("results", []))), None)
            if existing_entry:
                matched_r = next(r for r in existing_entry["results"] if r.get("platform") == platform and (r.get("url") or r.get("id")))
                already_url = matched_r.get("url") or matched_r.get("id")
        if already_url and not dry_run:
            print(f"  [{platform}] already posted at {already_url}, skipping duplicate publish.")
            results.append({"platform": platform, "url": already_url, "already_posted": True})
            continue
        text = text_for(platform, post, cfg)
        limit = CHAR_LIMITS.get(platform, 3000)
        if len(text) > limit:
            results.append({"platform": platform, "error": f"{len(text)} chars exceeds {limit}"})
            continue
        print(f"  [{platform}] {'DRY RUN, would post' if dry_run else 'posting'} {len(text)} chars: "
              + text[:110].replace("\n", " ") + ("..." if len(text) > 110 else ""))
        if dry_run:
            continue
        try:
            if platform == "linkedin" and post.get("document"):
                # Carousel: a PDF document post (assets/carousels/<slug>.pdf, committed to the repo).
                doc_path = str(ROOT / post["document"])
                print(f"  [linkedin] carousel document: {post['document']}")
                res = linkedin.publish_post(text, api_version=str(cfg["publish"].get("linkedin", {}).get("api_version", "202608")),
                                            document_path=doc_path,
                                            document_title=post.get("document_title") or post.get("source_title") or "Carousel")
            elif platform == "linkedin":
                img, alt = _linkedin_card(post)
                print(f"  [linkedin] share card: {img or 'NONE (posting text only)'}")
                res = linkedin.publish_post(text, api_version=str(cfg["publish"].get("linkedin", {}).get("api_version", "202608")),
                                            image_path=img, image_alt=alt)
            elif platform == "bluesky":
                from . import bluesky
                res = bluesky.post(text, images=_media_paths(post) or None, alts=post.get("image_alts"))
            elif platform == "threads":
                from . import threads
                img_url, alt = _threads_media_url(post)
                res = threads.post(text, images=[img_url] if img_url else None, alts=[alt])
            else:
                res = {"platform": platform, "error": f"no adapter for {platform} yet"}
        except Exception as e:  # noqa: BLE001
            res = {"platform": platform, "error": str(e)[:600]}
        results.append(res)
    if not dry_run and results and all(r.get("url") for r in results):
        post["status"] = "posted"
        post["posted_urls"] = {**(post.get("posted_urls") or {}), **{r["platform"]: r["url"] for r in results}}
        shorts.save_batch(batch, cfg)
    return results


def _publish_long(item: dict, cfg: dict, dry_run: bool) -> list[dict]:
    # Standalone carousel support for Instagram
    c_slug = item.get("carousel") or item.get("slug")
    c_json = DATA / "carousels" / f"{c_slug}.json"
    if "instagram" in item.get("platforms", []) and c_json.exists() and not (ROOT / "drafts" / item.get("slug", "") / "post.md").exists():
        from . import instagram as IG
        from ..carousel import render as R
        import json
        # Duplicate protection: skip if this carousel was already published to Instagram
        if not dry_run:
            pub_log = load_json(PUBLISH_LOG, []) or []
            existing_ig = next((l for l in pub_log if (l.get("item") == f"{c_slug} -> instagram" or f"{c_slug}" in str(l.get("item", "")))
                               and any(r.get("platform") == "instagram" and r.get("url") for r in l.get("results", []))), None)
            if existing_ig:
                matched_r = next(r for r in existing_ig["results"] if r.get("platform") == "instagram" and r.get("url"))
                print(f"  [instagram] already published at {matched_r['url']}, skipping duplicate publish.")
                return [{"platform": "instagram", "url": matched_r["url"], "already_posted": True}]

        print(f"  [instagram] {'DRY RUN, would publish carousel' if dry_run else 'publishing carousel'}: {c_slug}")
        if not dry_run:
            try:
                pdf_path = ROOT / "assets" / "carousels" / f"{c_slug}.pdf"
                if not pdf_path.exists():
                    pdf_path = R.render(c_json)
                out_dir = ROOT / "assets" / "carousel" / "instagram" / c_slug
                slides = IG.export_carousel_slides(pdf_path, out_dir, 1080, 1350)
                c_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
                c_key = os.environ.get("CLOUDINARY_API_KEY")
                c_sec = os.environ.get("CLOUDINARY_API_SECRET")
                ig_id = os.environ.get("INSTAGRAM_ACCOUNT_ID")
                tok = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
                uploaded = [IG.upload_to_cloudinary(s, c_name, c_key, c_sec) for s in slides]
                time.sleep(10)  # Allow Cloudinary CDN replication across edges before Instagram fetches
                deck = json.loads(c_json.read_text(encoding="utf-8"))
                cap = deck.get("caption") or deck.get("title")
                res = IG.publish_carousel([u["url"] for u in uploaded], cap, ig_id, tok)
                return [{"platform": "instagram", "url": res.get("permalink")}]
            except Exception as e:
                return [{"platform": "instagram", "error": str(e)[:600]}]
        return [{"platform": "instagram", "url": f"https://instagram.com/p/preview-{c_slug}"}]

    from .publisher import run as publish_run
    d = load_draft(item["slug"])
    results = []
    blog_platforms = [p for p in item["platforms"] if p in ("devto", "hashnode", "medium", "blogger")]
    if blog_platforms:
        if dry_run:
            print(f"  [{','.join(blog_platforms)}] DRY RUN, would publish live: {d['meta']['title']}")
        else:
            results += publish_run(item["slug"], blog_platforms, cfg, live=True, confirm=True)
            d = load_draft(item["slug"])  # canonical_url may have been set
    if "linkedin" in item["platforms"]:
        canonical = d["meta"].get("canonical_url")
        text = with_signature(d["linkedin"].replace("[LINK]", canonical or ""), cfg, "linkedin")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        import os
        from .media import resolve_media
        # The draft's own cover image (frontmatter `cover_image`: a repo path or URL) makes an image post;
        # without one the post carries LinkedIn's link card for the article instead.
        candidates = [c for c in (d["meta"].get("cover_image"),) if c]
        print(f"  [linkedin] {'DRY RUN, would post' if dry_run else 'posting'} {len(text)} chars"
              + (f" + cover image {candidates[0]}" if candidates else " + article link card"))
        if not dry_run:
            try:
                img = None
                for c in candidates:
                    try:
                        img = resolve_media([c])[0]
                        if not os.path.exists(img):
                            raise FileNotFoundError(img)
                        break
                    except Exception as e:  # noqa: BLE001 — fall back to the link card
                        img = None
                        print(f"  [linkedin] cover image unavailable ({str(e)[:80]}), using the link card")
                if img:
                    results.append(linkedin.publish_post(text, image_path=img, image_alt=d["meta"]["title"],
                                                         api_version=str(cfg["publish"].get("linkedin", {}).get("api_version", "202608"))))
                else:
                    results.append(linkedin.publish_post(text, article_url=canonical, article_title=d["meta"]["title"],
                                                         article_description=d["meta"].get("subtitle"),
                                                         api_version=str(cfg["publish"].get("linkedin", {}).get("api_version", "202608"))))
            except Exception as e:  # noqa: BLE001
                results.append({"platform": "linkedin", "error": str(e)[:600]})
    if "bluesky" in item["platforms"]:
        from . import bluesky
        canonical = d["meta"].get("canonical_url") or ""
        blurb = (d["meta"].get("subtitle") or d["meta"]["title"]).strip()
        text = (blurb[: 300 - len(canonical) - 2] + "\n" + canonical).strip() if canonical else blurb[:300]
        print(f"  [bluesky] {'DRY RUN, would post' if dry_run else 'posting'} {len(text)} chars")
        if not dry_run:
            try:
                results.append(bluesky.post(text))
            except Exception as e:  # noqa: BLE001
                results.append({"platform": "bluesky", "error": str(e)[:600]})
    if "threads" in item["platforms"]:
        from . import threads
        canonical = d["meta"].get("canonical_url") or ""
        blurb = (d["meta"].get("subtitle") or d["meta"]["title"]).strip()
        text = (blurb[: 500 - len(canonical) - 2] + "\n" + canonical).strip() if canonical else blurb[:500]
        cover = d["meta"].get("cover_image") or ""
        img_url = cover if cover.startswith(("http://", "https://")) else ""  # Threads needs a public URL
        print(f"  [threads] {'DRY RUN, would post' if dry_run else 'posting'} {len(text)} chars"
              + (f" + image {img_url}" if img_url else ""))
        if not dry_run:
            try:
                results.append(threads.post(text, images=[img_url] if img_url else None, alts=[d["meta"]["title"]]))
            except Exception as e:  # noqa: BLE001
                results.append({"platform": "threads", "error": str(e)[:600]})
    if "instagram" in item["platforms"]:
        from . import instagram as IG
        from ..carousel import render as R
        import json
        c_slug = item.get("carousel") or item.get("slug")
        json_path = DATA / "carousels" / f"{c_slug}.json"
        if json_path.exists():
            print(f"  [instagram] {'DRY RUN, would publish carousel' if dry_run else 'publishing carousel'}: {c_slug}")
            if not dry_run:
                try:
                    pdf_path = ROOT / "assets" / "carousels" / f"{c_slug}.pdf"
                    if not pdf_path.exists():
                        pdf_path = R.render(json_path)
                    out_dir = ROOT / "assets" / "carousel" / "instagram" / c_slug
                    slides = IG.export_carousel_slides(pdf_path, out_dir, 1080, 1350)
                    c_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
                    c_key = os.environ.get("CLOUDINARY_API_KEY")
                    c_sec = os.environ.get("CLOUDINARY_API_SECRET")
                    ig_id = os.environ.get("INSTAGRAM_ACCOUNT_ID")
                    tok = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
                    uploaded = [IG.upload_to_cloudinary(s, c_name, c_key, c_sec) for s in slides]
                    time.sleep(2)  # Allow Cloudinary CDN replication before Instagram fetches
                    deck = json.loads(json_path.read_text(encoding="utf-8"))
                    cap = deck.get("caption") or deck.get("title")
                    res = IG.publish_carousel([u["url"] for u in uploaded], cap, ig_id, tok)
                    results.append({"platform": "instagram", "url": res.get("permalink")})
                except Exception as e:  # noqa: BLE001
                    results.append({"platform": "instagram", "error": str(e)[:600]})
    return results


# ----------------------------------------------------------------------------- run

def run(cfg: dict, dry_run: bool = False, max_late_hours: int | None = None, only_item: str | None = None) -> list[dict]:
    q = load_queue()
    now = _now()
    late_limit = dt.timedelta(hours=max_late_hours or int(cfg["publish"].get("queue", {}).get("max_late_hours", 24)))
    if only_item:
        due = [i for i in q if i["id"] == only_item]
    else:
        due = sorted((i for i in q if i["status"] == "queued" and dt.datetime.fromisoformat(i["scheduled_at"]) <= now),
                     key=lambda i: i["scheduled_at"])
    if not due:
        print(f"[{now}] queue: nothing due ({sum(1 for i in q if i['status'] == 'queued')} queued)")
        return []
    done = []
    posted_by_platform: dict[str, int] = {}
    for item in due:
        when = dt.datetime.fromisoformat(item["scheduled_at"])
        label = _label(item)
        # Double-publish guard: if item is already logged as published, mark posted and never publish again
        pub_log = load_json(PUBLISH_LOG, []) or []
        existing_log = next((l for l in pub_log
                            if (l.get("item") == label or (item.get("carousel") and l.get("item") == f"{item.get('carousel')} -> instagram"))
                            and any(r.get("url") or r.get("id") for r in l.get("results", []))), None)
        if existing_log and not dry_run:
            print(f"[{now}] {item['id']} {label}: ALREADY PUBLISHED ({existing_log.get('at')}) -> marking posted without re-publishing.")
            item["status"] = "posted"
            item["results"] = existing_log.get("results", [])
            done.append(item)
            continue

        if not only_item and now - when > late_limit:
            item["status"] = "skipped"
            item["results"].append({"at": now.isoformat(), "error": f"overdue by more than {late_limit}; not posted"})
            print(f"[{now}] {item['id']} {label}: skipped (was due {when})")
            done.append(item)
            continue
        # Per-run caps: LinkedIn 2, Bluesky 3, Threads 2, others 1. GitHub's schedule trigger only fires
        # ~5-7 times/day on this repo (measured Sep 2026), so per-run capacity x runs/day must exceed the
        # daily queued volume, or the backlog grows until items pass max_late_hours and get SKIPPED.
        # LinkedIn demand is ~7/day (6 text + 1 carousel); at cap 1 that sat exactly at the edge with zero
        # headroom -- one 5-run day starts a permanent deficit and silent skips ~2 days later. Cap 2 gives
        # 10-14/day. A run that posts a second LinkedIn item waits linkedin_spacing_s first so the two posts
        # are not 20 seconds apart; the wait only ever happens when there is an actual backlog to clear.
        caps = {"linkedin": 2, "bluesky": 3, "threads": 2, "instagram": 2}
        linkedin_spacing_s = 90
        primary = item["platforms"][0] if item.get("platforms") else "linkedin"
        if posted_by_platform.get(primary, 0) >= caps.get(primary, 1):
            print(f"[{now}] {item['id']} {label}: deferred to next run ({primary} cap {caps.get(primary, 1)} per run)")
            continue
        if primary == "linkedin" and posted_by_platform.get(primary, 0) >= 1 and not dry_run:
            print(f"[{now}] {item['id']} {label}: second LinkedIn item this run -- waiting {linkedin_spacing_s}s to space the posts")
            time.sleep(linkedin_spacing_s)
        print(f"[{now}] {item['id']} {label}:")
        try:
            results = _publish_long(item, cfg, dry_run) if item.get("slug") else _publish_short(item, cfg, dry_run)
        except Exception as e:  # noqa: BLE001
            results = [{"platform": "*", "error": str(e)[:600]}]
        if dry_run:
            continue
        ok = [r for r in results if r.get("url") or r.get("file")]
        bad = [r for r in results if r.get("error")]
        for r in ok:
            print(f"  ok -> {r.get('url') or r.get('file')}")
        for r in bad:
            print(f"  FAILED [{r.get('platform')}]: {r['error']}")
            if "401" in r["error"] or "expired" in r["error"].lower():
                print("  A token looks expired. Regenerate it and update .env / the GitHub secret.")
        item["status"] = "posted" if ok and not bad else ("partial" if ok else "failed")
        item["results"].extend([{"at": now.isoformat(), **r} for r in results])
        if ok:
            posted_by_platform[primary] = posted_by_platform.get(primary, 0) + 1
            log = load_json(PUBLISH_LOG, []) or []
            log.append({"item": label, "live": True, "results": results, "at": now.isoformat(), "via": "queue"})
            save_json(PUBLISH_LOG, log)
        done.append(item)
    if not dry_run:
        save_json(QUEUE_PATH, q)
    return done


def post_now(cfg: dict, batch: str | None = None, post_id: str | None = None, slug: str | None = None,
             platforms: tuple[str, ...] | None = None, dry_run: bool = False) -> list[dict]:
    """Publish one approved item immediately through the same path the scheduler uses."""
    q = load_queue()
    nums = [int(m.group(1)) for i in q for m in [re.match(r"Q(\d+)$", i.get("id", ""))] if m]
    new_id = f"Q{(max(nums) + 1 if nums else 1):03d}"   # never reuse an id already present in the queue
    if slug:
        c_json = DATA / "carousels" / f"{slug}.json"
        if not c_json.exists():
            d = load_draft(slug)
        plats = platforms or ("linkedin",)
        item = {"id": new_id, "slug": slug, "platforms": list(plats)}
    else:
        from ..generate import shorts
        b = shorts.load_batch(batch)
        p = next((x for x in b["posts"] if x["id"] == post_id), None)
        if not p:
            raise SystemExit(f"{batch}/{post_id} not found")
        plats = platforms or tuple(p.get("platforms") or ["linkedin"])
        item = {"id": new_id, "batch": batch, "post_id": post_id, "platforms": list(plats)}
    item.update({"scheduled_at": _now().isoformat(timespec="minutes"), "status": "queued",
                 "created": _now().isoformat(timespec="minutes"), "results": [], "via": "post-now"})
    if dry_run:
        print(f"[dry run] {_label(item)}")
        return _publish_long(item, cfg, True) if slug else _publish_short(item, cfg, True)
    q.append(item)
    save_json(QUEUE_PATH, q)
    return run(cfg, only_item=item["id"])


def fmt_table(q: list[dict]) -> str:
    if not q:
        return "queue is empty"
    lines = [f"{'id':<5} {'status':<8} {'scheduled (local)':<18} item"]
    for i in sorted(q, key=lambda i: i["scheduled_at"]):
        lines.append(f"{i['id']:<5} {i['status']:<8} {i['scheduled_at'].replace('T', ' '):<18} {_label(i)}")
    return "\n".join(lines)
