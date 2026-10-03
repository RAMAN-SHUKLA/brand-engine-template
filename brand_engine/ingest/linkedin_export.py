"""Parse LinkedIn's official data export ("Get a copy of your data").

Why the export and not scraping: it is complete (every post, article, position,
skill, honor, media link you ever added), it includes fields the public profile
hides, and it does not violate LinkedIn's terms or risk the account. Scraping the
logged-in profile gets you a fraction of this and can get the account restricted.

How to get it: LinkedIn -> Me -> Settings & Privacy -> Data privacy ->
"Get a copy of your data" -> "Download larger data archive". LinkedIn emails a
first ZIP within ~10 minutes and the complete one within 24 hours. Point this
module at the ZIP(s) or the folder you unzipped into.

Privacy: Connections, messages, invitations, ad-targeting and login data are
deliberately NOT parsed. This is about your own content only.
"""
from __future__ import annotations
import csv
import io
import mimetypes
import re
import zipfile
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# CSV base names we care about (case-insensitive). Everything else is ignored.
TABLES = [
    "Profile", "Positions", "Education", "Skills", "Certifications", "Projects", "Honors",
    "Courses", "Languages", "Publications", "Shares", "Rich_Media", "Recommendations_Received",
    "Endorsement_Received_Info", "Volunteering", "Organizations", "Patents", "Test Scores",
    "Learning", "Events", "Causes You Care About",
]
SKIP_HINTS = ("connections", "messages", "invitations", "ad_targeting", "logins", "email addresses",
              "phonenumbers", "phone numbers", "security challenges", "registration", "inferences",
              "whatsapp", "contacts", "ads clicked", "member_follows", "receipts", "jobs")


def _collect_files(path: Path) -> dict[str, bytes]:
    """Return {relative_lower_path: bytes} from a zip, a folder of zips, or an unzipped folder."""
    files: dict[str, bytes] = {}

    def add_zip(zp: Path):
        with zipfile.ZipFile(zp) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                if any(h in name.lower() for h in SKIP_HINTS):
                    continue
                files[name.lower()] = z.read(info)

    if path.is_file() and path.suffix.lower() == ".zip":
        add_zip(path)
    elif path.is_dir():
        for zp in path.glob("*.zip"):
            add_zip(zp)
        for f in path.rglob("*"):
            if f.is_file() and f.suffix.lower() != ".zip":
                rel = str(f.relative_to(path)).replace("\\", "/")
                if any(h in rel.lower() for h in SKIP_HINTS):
                    continue
                files[rel.lower()] = f.read_bytes()
    else:
        raise FileNotFoundError(f"Not a zip or folder: {path}")
    return files


def _read_csv(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace")
    lines = text.splitlines(keepends=True)
    # Some exports start with a "Notes:" preamble before the header row.
    start = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("Notes:") or "," not in s:
            start = i + 1
            continue
        break
    body = "".join(lines[start:])
    reader = csv.DictReader(io.StringIO(body))
    rows = []
    for row in reader:
        clean = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None}
        if any(clean.values()):
            rows.append(clean)
    return rows


def _find_table(files: dict[str, bytes], base: str) -> list[dict]:
    target = base.lower().replace(" ", "_")
    for name, raw in files.items():
        stem = Path(name).stem.lower().replace(" ", "_")
        if Path(name).suffix.lower() == ".csv" and stem == target:
            return _read_csv(raw)
    return []


def _articles(files: dict[str, bytes]) -> list[dict]:
    out = []
    for name, raw in files.items():
        if "/articles/" in f"/{name}" and name.endswith((".html", ".htm")):
            soup = BeautifulSoup(raw.decode("utf-8", errors="replace"), "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else Path(name).stem
            h1 = soup.find("h1")
            if h1 and h1.get_text(strip=True):
                title = h1.get_text(strip=True)
            for t in soup(["script", "style"]):
                t.decompose()
            text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
            images = [img.get("src") for img in soup.find_all("img") if img.get("src")]
            out.append({"file": name, "title": title, "text": text, "images": images})
    return out


def load_export(path: str | Path) -> dict:
    files = _collect_files(Path(path))
    data: dict = {"source": str(path), "tables": {}, "articles": _articles(files),
                  "files_seen": sorted(files.keys())}
    for base in TABLES:
        rows = _find_table(files, base)
        if rows:
            data["tables"][base] = rows

    prof = (data["tables"].get("Profile") or [{}])[0]
    data["profile"] = {
        "first_name": prof.get("First Name"), "last_name": prof.get("Last Name"),
        "headline": prof.get("Headline"), "summary": prof.get("Summary"),
        "industry": prof.get("Industry"), "location": prof.get("Geo Location"),
        "websites": prof.get("Websites"),
    }
    shares = data["tables"].get("Shares", [])
    data["posts"] = [
        {"date": s.get("Date"), "url": s.get("ShareLink"), "text": s.get("ShareCommentary"),
         "shared_url": s.get("SharedUrl"), "media_url": s.get("MediaUrl"), "visibility": s.get("Visibility")}
        for s in shares if (s.get("ShareCommentary") or s.get("SharedUrl"))
    ]
    data["posts"].sort(key=lambda p: p.get("date") or "", reverse=True)
    media = {p["media_url"] for p in data["posts"] if p.get("media_url")}
    media |= {r.get("Media Link") for r in data["tables"].get("Rich_Media", []) if r.get("Media Link")}
    data["media_urls"] = sorted(media)
    data["stats"] = {k: len(v) for k, v in data["tables"].items()}
    data["stats"]["articles"] = len(data["articles"])
    data["stats"]["posts"] = len(data["posts"])
    return data


def download_media(export: dict, out_dir: Path, limit: int = 300) -> list[dict]:
    """Best-effort download of media referenced by your posts. Many LinkedIn CDN URLs
    expire or require a session; failures are recorded, not fatal."""
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, url in enumerate(export.get("media_urls", [])[:limit]):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            ctype = r.headers.get("content-type", "").split(";")[0]
            if r.status_code != 200 or not ctype.startswith(("image/", "video/", "application/pdf")):
                results.append({"url": url, "ok": False, "status": r.status_code, "type": ctype})
                continue
            ext = mimetypes.guess_extension(ctype) or ".bin"
            dest = out_dir / f"linkedin_media_{i:03d}{ext}"
            dest.write_bytes(r.content)
            results.append({"url": url, "ok": True, "path": str(dest), "bytes": len(r.content)})
        except Exception as e:  # noqa: BLE001
            results.append({"url": url, "ok": False, "error": str(e)[:200]})
    return results
