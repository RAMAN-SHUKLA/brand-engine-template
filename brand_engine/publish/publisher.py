"""Human-gated multi-platform publisher.

Defaults are deliberately conservative:
  * no --confirm  -> dry run: prints exactly what would be sent where, sends nothing
  * --confirm     -> creates DRAFTS on Dev.to and Hashnode (you press Publish in their UI), exports Medium HTML,
                     skips LinkedIn (it has no drafts)
  * --confirm --live -> publishes live on Dev.to/Hashnode and posts to LinkedIn
The primary platform (config.publish.primary_platform) is published first so its URL becomes the canonical
URL on every other platform (avoids duplicate-content penalties).
"""
from __future__ import annotations
import datetime as dt
import os
from pathlib import Path

from ..paths import ROOT, DRAFTS, PUBLISH_LOG, load_json, save_json, read_text, write_text
from ..util import split_frontmatter, join_frontmatter
from . import blogger, devto, hashnode, linkedin, medium


def load_draft(slug: str) -> dict:
    folder = DRAFTS / slug
    if not (folder / "post.md").exists():
        raise SystemExit(f"No draft at {folder}. Run `python cli.py status` to list drafts.")
    meta, body = split_frontmatter(read_text(folder / "post.md"))
    li = read_text(folder / "linkedin.txt") if (folder / "linkedin.txt").exists() else ""
    extra = load_json(folder / "meta.json", {}) or {}
    return {"folder": folder, "meta": meta, "body": body, "linkedin": li, "extra": extra}


def _order(platforms: list[str], primary: str) -> list[str]:
    return ([primary] if primary in platforms else []) + [p for p in platforms if p != primary]


def _blockers(draft: dict) -> list[str]:
    issues = []
    if "[FILL:" in draft["body"] or "[FILL:" in draft["linkedin"]:
        issues.append("draft still contains [FILL: ...] placeholders")
    for w in draft["extra"].get("warnings", []):
        if "unknown ids" in w or "not found anywhere" in w:
            issues.append(f"unresolved writer warning: {w}")
    return issues


def run(slug: str, platforms: list[str], cfg: dict, live: bool = False, confirm: bool = False,
        ignore_warnings: bool = False) -> list[dict]:
    d = load_draft(slug)
    pcfg = cfg["publish"]
    primary = pcfg.get("primary_platform", "devto")
    canonical = d["meta"].get("canonical_url")
    title, subtitle, tags = d["meta"]["title"], d["meta"].get("subtitle", ""), d["meta"].get("tags", [])
    results: list[dict] = []

    blockers = _blockers(d)
    if blockers and not ignore_warnings:
        print("Not publishing. Fix these first (or pass --ignore-warnings):")
        for b in blockers:
            print("  -", b)
        return results

    footer = (pcfg.get("devto_footer") or "").strip()
    if footer and footer.splitlines()[-1] not in d["body"]:
        d["body"] = d["body"].rstrip() + "\n\n" + footer + "\n"   # author box with links + email on every article

    print(f"\n{'LIVE PUBLISH' if live else 'DRAFT MODE'} {'(confirmed)' if confirm else '(DRY RUN - nothing is sent)'}")
    print(f"Draft: {slug}\nTitle: {title}\nTags: {tags}\nBody: {len(d['body'].split())} words | "
          f"LinkedIn: {len(d['linkedin'])} chars\nCanonical URL so far: {canonical}\n")

    for platform in _order(platforms, primary):
        print(f"--- {platform}")
        try:
            if platform == "devto":
                if not os.environ.get("DEVTO_API_KEY"):
                    print("  skipped: DEVTO_API_KEY not set"); continue
                print(f"  would create {'PUBLISHED' if live else 'DRAFT'} article; canonical={canonical if primary != 'devto' else '(self)'}")
                if not confirm:
                    continue
                res = devto.publish(title, d["body"], tags, published=live,
                                    canonical_url=None if primary == "devto" else canonical,
                                    description=subtitle, series=pcfg.get("devto", {}).get("series"),
                                    main_image=d["meta"].get("cover_image"))
            elif platform == "hashnode":
                if not os.environ.get("HASHNODE_TOKEN"):
                    print("  skipped: HASHNODE_TOKEN not set"); continue
                print(f"  would create {'PUBLISHED post' if live else 'DRAFT'}; canonical={canonical if primary != 'hashnode' else '(self)'}")
                if not confirm:
                    continue
                res = hashnode.publish(title, d["body"], tags, as_draft=not live, subtitle=subtitle,
                                       publication_id=pcfg.get("hashnode", {}).get("publication_id") or None,
                                       canonical_url=None if primary == "hashnode" else canonical)
            elif platform == "blogger":
                if not os.environ.get("BLOGGER_REFRESH_TOKEN"):
                    print("  skipped: BLOGGER_REFRESH_TOKEN not set (run `python cli.py blogger-auth`; README 'Blogger setup')"); continue
                blog_id = str(pcfg.get("blogger", {}).get("blog_id") or "")
                if not blog_id:
                    print("  skipped: publish.blogger.blog_id missing in config.yaml"); continue
                print(f"  would create {'PUBLISHED' if live else 'DRAFT'} Blogger post; canonical={canonical if primary != 'blogger' else '(self)'}")
                if not confirm:
                    continue
                res = blogger.publish(title, d["body"], tags, blog_id, published=live,
                                      canonical_url=None if primary == "blogger" else canonical)
            elif platform == "linkedin":
                if not live:
                    print("  skipped: LinkedIn has no drafts; rerun with --live --confirm when the article is up"); continue
                if not os.environ.get("LINKEDIN_ACCESS_TOKEN"):
                    print("  skipped: LINKEDIN_ACCESS_TOKEN not set"); continue
                commentary = d["linkedin"].replace("[LINK]", canonical or "").strip()
                print(f"  would post {len(commentary)} chars" + (f" with article card -> {canonical}" if canonical else " (no article link yet!)"))
                if not confirm:
                    continue
                img_path = d["meta"].get("image")
                if img_path and not os.path.isabs(img_path):
                    cand = d["folder"] / img_path
                    img_path = str(cand if cand.exists() else ROOT / img_path)
                res = linkedin.publish_post(commentary, article_url=canonical, article_title=title,
                                            article_description=subtitle,
                                            api_version=str(pcfg.get("linkedin", {}).get("api_version", "202508")),
                                            image_path=img_path,
                                            image_alt=d["meta"].get("image_alt") or title)
            elif platform == "medium":
                print("  will export medium.html + import instructions (Medium has no write API)")
                if not confirm:
                    continue
                res = medium.export_html(d["folder"], title, subtitle, d["body"], canonical)
            else:
                print(f"  unknown platform {platform}"); continue
        except Exception as e:  # noqa: BLE001
            res = {"platform": platform, "error": str(e)[:600]}
            print(f"  ERROR: {res['error']}")
        else:
            print(f"  ok: {res.get('url') or res.get('file') or res}")
            if platform == primary and live and res.get("url") and not canonical:
                canonical = res["url"]
                d["meta"]["canonical_url"] = canonical
        res["at"] = dt.datetime.now().isoformat(timespec="seconds")
        results.append(res)

    if confirm and results:
        d["meta"]["status"] = "published" if live else "drafted"
        write_text(d["folder"] / "post.md", join_frontmatter(d["meta"], d["body"]))
        prev = load_json(d["folder"] / "published.json", []) or []
        save_json(d["folder"] / "published.json", prev + results)
        log = load_json(PUBLISH_LOG, []) or []
        log.append({"slug": slug, "live": live, "results": results, "at": dt.datetime.now().isoformat(timespec="seconds")})
        save_json(PUBLISH_LOG, log)
    return results
