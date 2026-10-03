from __future__ import annotations
import os
import re
import shutil
import unicodedata
import yaml


def find_chrome() -> str | None:
    """Chrome/Chromium/Edge for headless rendering: $CHROME_PATH, then the usual install paths, then PATH."""
    env = os.environ.get("CHROME_PATH")
    if env and os.path.exists(env):
        return env
    for p in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ):
        if os.path.exists(p):
            return p
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "post"


def split_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return (yaml.safe_load(parts[1]) or {}), parts[2].lstrip("\n")
    return {}, text


def join_frontmatter(meta: dict, body: str) -> str:
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + body.rstrip() + "\n"


def numbers_in(text: str) -> set[str]:
    """Numeric tokens that look like claims: 14, 500+, 96.9%, 1,00,000, 3.2 GB."""
    found = set()
    for m in re.finditer(r"(?<![\w/.-])(\d[\d,]*(?:\.\d+)?)(\s?%|\+|\s?(?:GB|MB|ms|s|x|k|K|M|B|L|hrs?|min))?", text):
        num = m.group(1).replace(",", "")
        if num in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"} and not m.group(2):
            continue  # skip small list-like numbers
        if re.fullmatch(r"(19|20)\d\d", num):
            continue  # years are not claims
        found.add(num)
    return found
