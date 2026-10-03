"""brand-engine CLI. Full guide: README.md.

  python cli.py ingest [--resume bio.pdf] [--linkedin export.zip] [--sites URL ...] [--github USER]
  python cli.py batch new [--count 7] [--platform linkedin] [--notes "what's happening this week"]
  python cli.py batch list | batch show --week 2026-W41 | batch approve --week 2026-W41 [--drop P03] | batch schedule --week 2026-W41
  python cli.py calendar [--ai N] [--replace]
  python cli.py write --topic T003 | --title "..." [--angle "..."] [--pillar KEY] [--notes "..."]
  python cli.py approve --slug my-post
  python cli.py publish --slug my-post [--platforms devto,hashnode,blogger,linkedin,medium] [--confirm] [--live]
  python cli.py queue add --slug my-post --at "2026-10-09 10:00"   |  queue auto --days Tue,Thu --times 10:00
  python cli.py queue list | queue run [--dry-run] | queue remove --id Q001
  python cli.py ig-publish <deck-slug> [--confirm]
  python cli.py media-kit | status | sync
"""
from __future__ import annotations
import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from brand_engine.paths import ROOT, DATA, MEDIA, DRAFTS, CALENDAR_PATH, get_niche, load_config, load_json, save_json
from brand_engine.util import split_frontmatter

load_dotenv(ROOT / ".env")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def apply_timezone(cfg: dict) -> None:
    """Read every schedule time in config.yaml's `timezone` (no-op on Windows, which has no tzset)."""
    tz = cfg.get("timezone")
    if tz and hasattr(time, "tzset"):
        os.environ["TZ"] = tz
        time.tzset()


def cmd_ingest(a, cfg):
    icfg = cfg.get("ingest", {})
    if a.resume:
        from brand_engine.ingest.resume import parse_resume
        r = parse_resume(a.resume)
        save_json(DATA / "resume.json", r)
        print(f"resume: {len(r['text'])} chars, {len(r['links'])} links, sections: {list(r['sections'])}")
    if a.linkedin:
        from brand_engine.ingest.linkedin_export import load_export, download_media
        li = load_export(a.linkedin)
        save_json(DATA / "linkedin.json", li)
        print(f"linkedin export: {li['stats']}")
        if a.download_media:
            res = download_media(li, MEDIA)
            ok = sum(1 for x in res if x.get("ok"))
            save_json(DATA / "linkedin_media_download.json", res)
            print(f"media: {ok}/{len(res)} downloaded to {MEDIA}")
    if a.linkedin_urls:
        from brand_engine.ingest.linkedin_posts import URLS_FILE, fetch_all, merge_into_linkedin_json
        urls = [u.strip() for u in URLS_FILE.read_text(encoding="utf-8").splitlines() if u.strip().startswith("http")]
        posts = fetch_all(urls)
        ok = [p for p in posts if p.get("ok")]
        li = merge_into_linkedin_json(posts)
        print(f"linkedin public posts: {len(ok)}/{len(posts)} fetched -> {li['stats']['posts']} stored; "
              f"readable dump: {DATA / 'linkedin_posts.md'}")
        for p in posts:
            if not p.get("ok"):
                print(f"  failed: {p['url'][-40:]} status={p.get('status')} {p.get('error', '')}")
    gh_user = a.github or icfg.get("github_user")
    if gh_user and not a.skip_github:
        from brand_engine.ingest.github import fetch_github
        gh = fetch_github(gh_user, icfg.get("github_featured", []), icfg.get("github_max_readmes", 12))
        save_json(DATA / "github.json", gh)
        print(f"github: {len(gh['repos'])} repos, {sum(1 for r in gh['repos'] if r.get('readme'))} READMEs")
    sites = a.sites or icfg.get("website_urls", [])
    if sites and not a.skip_sites:
        from brand_engine.ingest.website import fetch_site
        ws = fetch_site(sites)
        save_json(DATA / "website.json", ws)
        print(f"website: {sum(1 for p in ws['pages'] if p.get('ok'))}/{len(ws['pages'])} pages fetched")
    from brand_engine.ingest.knowledge_base import build_knowledge_base
    kb = build_knowledge_base(cfg)
    print(f"knowledge base: {len(kb['facts'])} facts, {len(kb['projects'])} projects -> {DATA / 'knowledge_base.json'}")
    print(f"brand brief -> {DATA / 'brand_brief.md'}")


def cmd_calendar(a, cfg):
    from brand_engine.generate.calendar import build_calendar, expand_with_ai
    topics = build_calendar(cfg, replace=a.replace)
    if a.ai:
        topics = expand_with_ai(cfg, a.ai)
    for t in topics:
        print(f"{t['id']}  [{t['pillar']:<10}] {t['status']:<9} {t['title_idea']}")
    print(f"\n{len(topics)} topics -> {CALENDAR_PATH}")


def cmd_write(a, cfg):
    from brand_engine.generate.writer import write_post
    if a.topic:
        topics = load_json(CALENDAR_PATH, []) or []
        topic = next((t for t in topics if t["id"] == a.topic), None)
        if not topic:
            raise SystemExit(f"topic {a.topic} not in calendar; run `python cli.py calendar`")
    else:
        if not a.title:
            raise SystemExit("give --topic ID or --title")
        niche = get_niche(cfg)
        topic = {"id": None, "title_idea": a.title, "angle": a.angle or "", "pillar": a.pillar or niche["pillars"][0]["key"],
                 "fact_ids": [], "audience": a.audience or niche["audience"][0], "notes": a.notes}
    if a.model:
        cfg["writer"]["model"] = a.model
    folder = write_post(topic, cfg)
    meta = load_json(folder / "meta.json")
    print(f"\ndraft -> {folder}")
    print(f"model: {meta['usage'].get('model')} | tokens in/out: {meta['usage']['input_tokens']}/{meta['usage']['output_tokens']}"
          f" | cache read: {meta['usage'].get('cache_read_input_tokens')}")
    print(f"facts used: {meta['facts_used']}")
    if meta["claims_to_verify"]:
        print("claims the model flagged:"); [print("  -", c) for c in meta["claims_to_verify"]]
    if meta["warnings"]:
        print("post-check warnings:"); [print("  -", w) for w in meta["warnings"]]
    if a.topic:
        topics = load_json(CALENDAR_PATH, [])
        for t in topics:
            if t["id"] == a.topic:
                t["status"] = "drafted"; t["slug"] = folder.name
        save_json(CALENDAR_PATH, topics)


def cmd_publish(a, cfg):
    from brand_engine.publish.publisher import run
    platforms = [p.strip() for p in (a.platforms or ",".join(cfg["publish"]["platforms"])).split(",") if p.strip()]
    run(a.slug, platforms, cfg, live=a.live, confirm=a.confirm, ignore_warnings=a.ignore_warnings)


def cmd_approve(a, cfg):
    from brand_engine.publish.queue import approve
    meta = approve(a.slug, ignore_warnings=a.ignore_warnings)
    print(f"approved: {a.slug} (status={meta['status']}). Queue it with `python cli.py queue add --slug {a.slug} --at \"YYYY-MM-DD HH:MM\"`")


def cmd_queue(a, cfg):
    from brand_engine.publish import queue as Q
    if a.qcmd == "add":
        item = Q.add(a.slug, Q.parse_when(a.at), tuple((a.platforms or "linkedin").split(",")))
        print(f"queued {item['id']}: {item['slug']} at {item['scheduled_at']} -> {item['platforms']}")
    elif a.qcmd == "auto":
        qcfg = cfg["publish"].get("queue", {})
        days = (a.days or ",".join(qcfg.get("days", ["Tue", "Thu"]))).split(",")
        times = (a.times or ",".join(qcfg.get("times", ["10:00"]))).split(",")
        items = Q.auto_plan(days, times, Q.parse_when(a.start) if a.start else None)
        print(f"queued {len(items)} approved draft(s)")
        print(Q.fmt_table(Q.load_queue()))
    elif a.qcmd == "list":
        print(Q.fmt_table(Q.load_queue()))
    elif a.qcmd == "remove":
        print("removed" if Q.remove(a.id) else "no queued item with that id")
    elif a.qcmd == "run":
        Q.run(cfg, dry_run=a.dry_run, only_item=(a.only or None))
    elif a.qcmd == "post-now":
        plats = tuple(a.platforms.split(",")) if a.platforms else None
        Q.post_now(cfg, batch=a.batch, post_id=a.post_id, slug=a.slug, platforms=plats, dry_run=a.dry_run)


def cmd_batch(a, cfg):
    from brand_engine.generate import shorts as S
    from brand_engine.publish import queue as Q
    if a.bcmd == "new":
        from brand_engine.generate.writer import generate_batch
        week = a.week or S.week_id()
        folder = generate_batch(cfg, week, a.count, a.platform or "linkedin", a.notes or "", append=a.append)
        print(f"batch {week} -> {folder / 'review.md'}")
        print(f"Read it, then: python cli.py batch approve --week {week} [--drop P03]  ->  "
              f"python cli.py batch schedule --week {week}" + (f" --platform {a.platform}" if a.platform else ""))
    elif a.bcmd == "list":
        for w in S.list_batches():
            b = S.load_batch(w)
            st = {}
            for p in b["posts"]:
                st[p.get("status", "draft")] = st.get(p.get("status", "draft"), 0) + 1
            print(f"{w}: {len(b['posts'])} posts  {st}")
        if not S.list_batches():
            print("no batches yet")
    elif a.bcmd == "show":
        b = S.load_batch(a.week)
        print((S.batch_dir(a.week) / "review.md").read_text(encoding="utf-8"))
    elif a.bcmd == "approve":
        only = a.only.split(",") if a.only else None
        drop = a.drop.split(",") if a.drop else None
        print(S.approve(a.week, only=only, drop=drop, ignore_warnings=a.ignore_warnings))
        print(f"review file: {S.batch_dir(a.week) / 'review.md'}")
    elif a.bcmd == "schedule":
        qcfg = cfg["publish"].get("queue", {})
        platform = a.platform or "linkedin"
        days = (a.days or ",".join(qcfg.get("days", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]))).split(",")
        default_times = (qcfg.get("platform_times") or {}).get(platform) or qcfg.get("times", ["09:00", "18:30"])
        times = (a.times or ",".join(default_times)).split(",")
        items = S.schedule(a.week, days, times, Q.parse_when(a.start) if a.start else None, platform=platform)
        print(f"queued {len(items)} {platform} post(s) from {a.week} at {','.join(times)}")
        print(Q.fmt_table([i for i in Q.load_queue() if i["status"] == "queued"]))
    elif a.bcmd == "render":
        b = S.load_batch(a.week)
        print(S.save_batch(b, cfg) / "review.md")


def cmd_sync(a, cfg):
    """Pull the cloud runner's queue state, then push local approvals/schedules. Run after approve/schedule."""
    import subprocess
    # Force the gh credential helper on every call when gh is installed: when git runs from Python on Windows
    # the repo-local helper reset is not always honoured and the stale Windows Credential Manager entry gets used.
    gh_exe = (shutil.which("gh") or "").replace("\\", "/")
    helper = ["-c", "credential.helper=", "-c", f'credential.helper=!"{gh_exe}" auth git-credential'] if gh_exe else []
    # .env's GITHUB_TOKEN (used only for API rate limits) must not leak into git/gh, which would prefer it
    # over the logged-in gh account and fail if it is stale.
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    def git(*args, check=True):
        r = subprocess.run(["git", *helper, *args], cwd=ROOT, capture_output=True,
                           text=True, env=env)
        if r.stdout.strip():
            print(r.stdout.strip())
        if check and r.returncode != 0:
            raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
        return r
    git("pull", "--rebase", "--autostash")
    paths = ["data/post_queue.json", "data/publish_log.json", "data/batches", "data/manual_facts.yaml",
             "data/voice_samples.md", "data/carousels", "assets/carousels", "drafts", "config.yaml"]
    git("add", *[x for x in paths if (ROOT / x).exists()])  # git add fails on a path that doesn't exist yet
    diff = git("diff", "--cached", "--quiet", check=False)
    if diff.returncode != 0:
        git("commit", "-m", a.message or "content: update queue and batches")
    ahead = git("rev-list", "--count", "@{u}..HEAD", check=False).stdout.strip()
    if ahead and ahead != "0":
        git("push")
        print(f"pushed {ahead} commit(s). The cloud runner picks this up on its next run.")
    else:
        print("nothing new to push")


def cmd_bluesky_links(a, cfg):
    """Post the profile links as a 2-post thread and pin the first post (config.publish.bluesky.links_post[_reply])."""
    from brand_engine.publish import bluesky
    bcfg = cfg["publish"]["bluesky"]
    first, reply = bcfg["links_post"].strip(), (bcfg.get("links_post_reply") or "").strip()
    for label, t in (("links_post", first), ("links_post_reply", reply)):
        if len(t) > 300:
            raise SystemExit(f"{label} is {len(t)} chars; Bluesky's limit is 300")
    if a.dry_run:
        print(f"[dry run] would post {len(first)} chars, reply {len(reply)} chars, then pin the first post"); return
    session = bluesky.login()
    top = bluesky.post(first, session=session)
    print("posted:", top["url"])
    if reply:
        r = bluesky.post(reply, session=session, reply_to=top)
        print("reply:  ", r["url"])
    bluesky.pin_post(session, top["id"], top["cid"])
    print("pinned:", top["url"])


def cmd_linkedin_check(a, cfg):
    """Verify the token in .env works before anything is scheduled."""
    import os
    from brand_engine.publish.linkedin import get_person_urn
    tok = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    if not tok:
        raise SystemExit("LINKEDIN_ACCESS_TOKEN is not set in .env")
    urn = get_person_urn(tok)
    print(f"token OK. Posts will be authored as {urn}, i.e. your PERSONAL profile (a Page would be urn:li:organization:...).")


def cmd_blogger_auth(a, cfg):
    """One-time Google OAuth for Blogger: opens the consent page, saves BLOGGER_REFRESH_TOKEN to .env,
    verifies the blog, then prints the three `gh secret set` commands for the cloud runner."""
    import os
    from brand_engine.paths import ROOT
    from brand_engine.publish import blogger
    cid, sec = os.environ.get("BLOGGER_CLIENT_ID"), os.environ.get("BLOGGER_CLIENT_SECRET")
    if not (cid and sec):
        raise SystemExit("Fill BLOGGER_CLIENT_ID and BLOGGER_CLIENT_SECRET in .env first (README 'Blogger setup', step 1-2).")
    tok = blogger.auth_flow(cid, sec, open_browser=not a.no_browser)
    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    lines = [l for l in lines if not l.startswith("BLOGGER_REFRESH_TOKEN=")]
    lines.append(f"BLOGGER_REFRESH_TOKEN={tok['refresh_token']}")
    env_path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    os.environ["BLOGGER_REFRESH_TOKEN"] = tok["refresh_token"]
    info = blogger.blog_info(str(cfg["publish"]["blogger"]["blog_id"]))
    print(f"\nOK: BLOGGER_REFRESH_TOKEN saved to .env. Blog: {info.get('name')} -> {info.get('url')} "
          f"({info.get('posts', {}).get('totalItems', 0)} posts so far)")
    print("\nNow give the cloud runner the same three values (Git Bash / the app's Run button; reads .env, prints nothing):")
    for k in ("BLOGGER_CLIENT_ID", "BLOGGER_CLIENT_SECRET", "BLOGGER_REFRESH_TOKEN"):
        print(f'  gh secret set {k} --body "$(grep ^{k}= .env | cut -d= -f2-)"')
    print("\nThen: python cli.py blogger-check  ->  python scripts/queue_blogger.py --dry-run  ->  (no --dry-run)  ->  python cli.py sync")


def cmd_blogger_check(a, cfg):
    """Verify the Blogger token + blog id work (mints an access token from the refresh token, reads the blog)."""
    from brand_engine.publish import blogger
    info = blogger.blog_info(str(cfg["publish"]["blogger"]["blog_id"]))
    print(f"token OK. Blog: {info.get('name')} -> {info.get('url')} ({info.get('posts', {}).get('totalItems', 0)} posts)")


def cmd_ig_check(a, cfg):
    """Verify Instagram Graph API credentials and account info."""
    import os, requests
    from dotenv import load_dotenv
    load_dotenv()
    tok = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    ig_id = os.environ.get("INSTAGRAM_ACCOUNT_ID")
    if not (tok and ig_id):
        raise SystemExit("INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_ACCOUNT_ID is missing in .env")
    r = requests.get(f"https://graph.facebook.com/v21.0/{ig_id}?fields=username,name,profile_picture_url&access_token={tok}").json()
    if "username" in r:
        print(f"Instagram OK: @{r['username']} ({r.get('name')}) · ID: {ig_id}")
    else:
        print("Instagram error:", r)


def cmd_ig_publish(a, cfg):
    """Publish a carousel deck to Instagram as 1080x1350 JPEG slides."""
    import os, json, time
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv()
    from brand_engine.paths import ROOT, DATA
    from brand_engine.carousel import render as R
    from brand_engine.publish import instagram as IG

    slug = a.slug
    json_path = DATA / "carousels" / f"{slug}.json"
    if not json_path.exists():
        raise SystemExit(f"No carousel found at {json_path}")

    deck = json.loads(json_path.read_text(encoding="utf-8"))
    pdf_path = ROOT / "assets" / "carousels" / f"{slug}.pdf"
    if not pdf_path.exists():
        print(f"Rendering PDF for {slug}...")
        pdf_path = R.render(json_path)

    out_dir = ROOT / "assets" / "carousel" / "instagram" / slug
    slides = IG.export_carousel_slides(pdf_path, out_dir, 1080, 1350)
    handle = cfg.get("person", {}).get("handle")
    print(f"Exported {len(slides)} slides (1080x1350)" + (f" for @{handle}" if handle else ""))

    if not a.confirm:
        print(f"\n[DRY RUN] Would publish {len(slides)} slides to Instagram.")
        print(f"To publish live, re-run with: python cli.py ig-publish {slug} --confirm")
        return

    c_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    c_key = os.environ.get("CLOUDINARY_API_KEY")
    c_sec = os.environ.get("CLOUDINARY_API_SECRET")
    ig_id = os.environ.get("INSTAGRAM_ACCOUNT_ID")
    tok = os.environ.get("INSTAGRAM_ACCESS_TOKEN")

    uploaded = []
    for s in slides:
        print(f"  uploading {s.name} to Cloudinary...")
        res = IG.upload_to_cloudinary(s, c_name, c_key, c_sec)
        uploaded.append(res)

    caption = a.caption or deck.get("caption") or deck.get("title")
    urls = [u["url"] for u in uploaded]
    time.sleep(2)
    print(f"Publishing {len(urls)} slides live to Instagram ({ig_id})...")
    res = IG.publish_carousel(urls, caption, ig_id, tok)
    print("\nSUCCESS: Published live to Instagram!")
    print(f"Permalink: {res.get('permalink')}")


def cmd_media_kit(a, cfg):
    from brand_engine.outreach.media_kit import build_media_kit
    print(build_media_kit(cfg))


def cmd_status(a, cfg):
    kb = load_json(DATA / "knowledge_base.json")
    print("knowledge base:", f"{len(kb['facts'])} facts, generated {kb['generated_at']}, sources {kb['sources']}" if kb else "missing")
    topics = load_json(CALENDAR_PATH, []) or []
    print(f"calendar: {len(topics)} topics ({sum(1 for t in topics if t['status'] == 'planned')} planned)")
    print("drafts:")
    for folder in sorted(DRAFTS.iterdir()) if DRAFTS.exists() else []:
        post = folder / "post.md"
        if post.exists():
            meta, _ = split_frontmatter(post.read_text(encoding="utf-8"))
            pub = load_json(folder / "published.json", []) or []
            where = ", ".join(f"{r['platform']}{'' if r.get('published') else '(draft)'}" for r in pub if not r.get("error"))
            print(f"  {folder.name:<60} {meta.get('status', '?'):<10} {where}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest"); s.set_defaults(fn=cmd_ingest)
    s.add_argument("--resume", help="a PDF about you: resume, bio or media kit"); s.add_argument("--linkedin", help="LinkedIn export .zip or folder")
    s.add_argument("--github"); s.add_argument("--sites", nargs="*")
    s.add_argument("--linkedin-urls", action="store_true", help="fetch your public posts listed in data/linkedin_post_urls.txt")
    s.add_argument("--download-media", action="store_true"); s.add_argument("--skip-github", action="store_true")
    s.add_argument("--skip-sites", action="store_true")

    s = sub.add_parser("calendar"); s.set_defaults(fn=cmd_calendar)
    s.add_argument("--ai", type=int, default=0, help="ask Claude for N extra topics"); s.add_argument("--replace", action="store_true")

    s = sub.add_parser("write"); s.set_defaults(fn=cmd_write)
    s.add_argument("--topic"); s.add_argument("--title"); s.add_argument("--angle"); s.add_argument("--pillar")
    s.add_argument("--notes"); s.add_argument("--model")
    s.add_argument("--audience", help="default: the first niche.audience in config.yaml")

    s = sub.add_parser("publish"); s.set_defaults(fn=cmd_publish)
    s.add_argument("--slug", required=True); s.add_argument("--platforms")
    s.add_argument("--confirm", action="store_true", help="actually send (default is dry run)")
    s.add_argument("--live", action="store_true", help="publish publicly instead of creating drafts")
    s.add_argument("--ignore-warnings", action="store_true")

    s = sub.add_parser("approve", help="mark a reviewed draft as ready to queue"); s.set_defaults(fn=cmd_approve)
    s.add_argument("--slug", required=True); s.add_argument("--ignore-warnings", action="store_true")

    s = sub.add_parser("queue", help="schedule approved drafts and run the poster"); s.set_defaults(fn=cmd_queue)
    qs = s.add_subparsers(dest="qcmd", required=True)
    x = qs.add_parser("add"); x.add_argument("--slug", required=True); x.add_argument("--at", required=True, help='"YYYY-MM-DD HH:MM" local')
    x.add_argument("--platforms", default="linkedin")
    x = qs.add_parser("auto", help="fill upcoming slots with every approved draft")
    x.add_argument("--days", help="e.g. Mon,Wed,Fri (default: config publish.queue.days)")
    x.add_argument("--times", help="e.g. 09:00,18:30 (default: config publish.queue.times)"); x.add_argument("--start")
    qs.add_parser("list")
    x = qs.add_parser("remove"); x.add_argument("--id", required=True)
    x = qs.add_parser("run", help="post everything that is due (called by the scheduler)"); x.add_argument("--dry-run", action="store_true")
    x.add_argument("--only", help="post this one queue item now regardless of schedule, e.g. Q123")
    x = qs.add_parser("post-now", help="publish one approved item immediately")
    x.add_argument("--batch"); x.add_argument("--post-id"); x.add_argument("--slug"); x.add_argument("--dry-run", action="store_true")
    x.add_argument("--platforms", help="override: linkedin,bluesky,devto,...")

    s = sub.add_parser("batch", help="weekly batches of short posts (LinkedIn, Threads, Bluesky)"); s.set_defaults(fn=cmd_batch)
    bs = s.add_subparsers(dest="bcmd", required=True)
    x = bs.add_parser("new", help="write a batch of short posts with Claude from your niche and facts")
    x.add_argument("--week", help="batch name, default: this ISO week (e.g. 2026-W41)")
    x.add_argument("--count", type=int, default=7, help="how many posts (default 7)")
    x.add_argument("--platform", help="linkedin (default) | threads | bluesky")
    x.add_argument("--notes", help="what is happening this week: launches, events, ideas, things to mention")
    x.add_argument("--append", action="store_true", help="add posts to an existing batch")
    bs.add_parser("list")
    x = bs.add_parser("show"); x.add_argument("--week", required=True)
    x = bs.add_parser("approve"); x.add_argument("--week", required=True)
    x.add_argument("--only", help="P01,P02 ..."); x.add_argument("--drop", help="P03,P09 ...")
    x.add_argument("--ignore-warnings", action="store_true")
    x = bs.add_parser("schedule"); x.add_argument("--week", required=True)
    x.add_argument("--platform", help="linkedin (default) | threads | bluesky; uses publish.queue.platform_times")
    x.add_argument("--days"); x.add_argument("--times"); x.add_argument("--start")
    x = bs.add_parser("render"); x.add_argument("--week", required=True)

    s = sub.add_parser("sync", help="git pull + push queue/batches so the cloud runner sees them"); s.set_defaults(fn=cmd_sync)
    s.add_argument("-m", "--message")

    s = sub.add_parser("bluesky-links", help="post + pin the profile links thread"); s.set_defaults(fn=cmd_bluesky_links)
    s.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("linkedin-check", help="verify LINKEDIN_ACCESS_TOKEN works"); s.set_defaults(fn=cmd_linkedin_check)
    s = sub.add_parser("blogger-auth", help="one-time Google OAuth for Blogger; saves BLOGGER_REFRESH_TOKEN to .env"); s.set_defaults(fn=cmd_blogger_auth)
    s.add_argument("--no-browser", action="store_true", help="print the consent URL instead of opening a browser")
    s = sub.add_parser("blogger-check", help="verify the Blogger token + blog id work"); s.set_defaults(fn=cmd_blogger_check)

    s = sub.add_parser("ig-check", help="verify INSTAGRAM_ACCESS_TOKEN + account id"); s.set_defaults(fn=cmd_ig_check)
    s = sub.add_parser("ig-publish", help="publish a carousel deck to Instagram"); s.set_defaults(fn=cmd_ig_publish)
    s.add_argument("slug", help="carousel slug (data/carousels/<slug>.json)")
    s.add_argument("--confirm", action="store_true", help="publish live to Instagram (omit for dry run)")
    s.add_argument("--caption", help="optional custom caption override")

    s = sub.add_parser("media-kit", help="one-page media kit for brands and collaborators"); s.set_defaults(fn=cmd_media_kit)

    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)

    a = ap.parse_args(argv)
    cfg = load_config()
    apply_timezone(cfg)
    a.fn(a, cfg)


if __name__ == "__main__":
    main()
