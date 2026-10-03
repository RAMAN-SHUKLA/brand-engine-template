"""Render editorial framed share cards (1200x630):
- Left white rounded card with category kicker, prominent serif headline, and author credentials
- Right rounded card with a photo of you (e.g. from assets/me/)
- Soft light-blue/grey background
Author name and credentials default to `person` in config.yaml.
"""
from __future__ import annotations
import subprocess
import html
from pathlib import Path

from ..paths import load_config
from ..util import find_chrome

ROOT = Path(__file__).resolve().parents[2]
CARDS_DIR = ROOT / "assets" / "cards"
CARDS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_HTML = ROOT / "scratch" / "card_render_temp.html"
TEMP_HTML.parent.mkdir(parents=True, exist_ok=True)

CHROME = find_chrome()


def _default_author() -> tuple[str, str]:
    """(name, "headline · location · github") from config.yaml's `person`."""
    p = load_config().get("person", {})
    github = (p.get("links", {}).get("github") or "").replace("https://", "").replace("http://", "").rstrip("/")
    meta = " · ".join(x for x in (p.get("headline", "").split("|")[0].strip(), p.get("location", ""), github) if x)
    return p.get("name", ""), meta


def build_card_html(kicker: str, title: str, photo_path: str, author_name: str, author_meta: str) -> str:
    # Resolve photo file URL
    p = Path(photo_path)
    if not p.is_absolute():
        p = ROOT / p
    photo_url = p.resolve().as_uri()

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    width: 1200px;
    height: 630px;
    background-color: #EBF0F6;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    overflow: hidden;
  }}
  .container {{
    width: 1136px;
    height: 566px;
    display: flex;
    gap: 24px;
  }}
  .left-card {{
    flex: 1.25;
    background: #FFFFFF;
    border-radius: 28px;
    padding: 48px 44px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03);
  }}
  .kicker-row {{
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .kicker-dot {{
    width: 9px;
    height: 9px;
    background-color: #FF5A36;
    border-radius: 50%;
    display: inline-block;
  }}
  .kicker-text {{
    color: #FF5A36;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 2.5px;
    text-transform: uppercase;
  }}
  .title-text {{
    font-family: "Georgia", "Newsreader", "Times New Roman", serif;
    font-size: 43px;
    font-weight: 600;
    line-height: 1.22;
    color: #1A1A1E;
    letter-spacing: -0.4px;
    margin-top: -10px;
  }}
  .author-block {{
    display: flex;
    flex-direction: column;
    gap: 5px;
  }}
  .author-name {{
    font-size: 22px;
    font-weight: 700;
    color: #111111;
    letter-spacing: -0.2px;
  }}
  .author-meta {{
    font-size: 15px;
    color: #6E6E73;
    font-weight: 400;
    letter-spacing: -0.1px;
  }}
  .right-card {{
    flex: 0.95;
    border-radius: 28px;
    overflow: hidden;
    background-color: #151515;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
  }}
  .photo {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center top;
    display: block;
  }}
</style>
</head>
<body>
<div class="container">
  <div class="left-card">
    <div class="kicker-row">
      <span class="kicker-dot"></span>
      <span class="kicker-text">{html.escape(kicker.upper())}</span>
    </div>
    <div class="title-text">
      {html.escape(title)}
    </div>
    <div class="author-block">
      <div class="author-name">{html.escape(author_name)}</div>
      <div class="author-meta">{html.escape(author_meta)}</div>
    </div>
  </div>
  <div class="right-card">
    <img class="photo" src="{photo_url}" alt="{html.escape(title)}" />
  </div>
</div>
</body>
</html>"""


def render_card(kicker: str, title: str, photo_path: str, output_path: str,
                author_name: str | None = None, author_meta: str | None = None) -> Path:
    out = Path(output_path)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)

    if author_name is None or author_meta is None:
        default_name, default_meta = _default_author()
        author_name = default_name if author_name is None else author_name
        author_meta = default_meta if author_meta is None else author_meta
    html_code = build_card_html(kicker, title, photo_path, author_name, author_meta)
    TEMP_HTML.write_text(html_code, encoding="utf-8")

    if not CHROME:
        raise RuntimeError("Google Chrome or Microsoft Edge is required for card rendering")

    file_url = TEMP_HTML.resolve().as_uri()
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--window-size=1200,630",
        f"--screenshot={str(out)}",
        file_url
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if not out.exists() or out.stat().st_size < 5000:
        raise RuntimeError(f"Card render failed for {output_path}: {res.stderr}")
    return out


if __name__ == "__main__":
    test_out = CARDS_DIR / "card_test.png"
    avatar = load_config().get("person", {}).get("avatar") or "assets/me/avatar.jpg"
    if not (ROOT / avatar).exists():
        avatar = "assets/carousel/avatar-placeholder.jpg"
    render_card(
        kicker="Content Systems",
        title="How to batch a week of content in 90 minutes",
        photo_path=avatar,
        output_path=str(test_out)
    )
    print("Test card rendered successfully:", test_out, test_out.stat().st_size)
