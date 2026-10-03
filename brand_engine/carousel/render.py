"""Render a carousel deck (data/carousels/<slug>.json) to a 1080x1350 PDF + PNG previews.

Usage:
    python -m brand_engine.carousel.render data/carousels/example-deck.json
    python -m brand_engine.carousel.render --all

Slide types (each slide is a dict with "type"; every content slide also gets the author chip,
the big handwritten slide number and the footer automatically):

  cover    : {kicker, title:[[text, style]], subtitle, photo, photo_mode: "photo"|"split"|"cutout", face?: [x,y,w,h]}
  points   : {title:[[...]], intro?, bullets:[str], icon?, note?, note_label?, sticker?, photo?}
  compare  : {title, left:{label, items|text}, right:{label, items|text}, note?, photo?}
  stats    : {title, tiles:[{value,label}], intro?, note?, photo?}
  shot     : {title, image, url?, caption?, bullets?, note?}
  steps    : {title, steps:[{title, desc}], intro?, note?, photo?}
  quote    : {text, by, photo?}
  gallery  : {title, images:[{src, caption}], intro?, note?}
  cta      : {headline:[[...]], url, lines:[str], photo?, qr?: bool}
  photo    : {title:[[...]], photo, intro?, lines:[str], caption?}  -- full-bleed photo slide; the text
             sits in the bottom 40% (white on a shade) when the face fits the top half, otherwise the
             photo becomes a 700px top panel with the text on paper below it. Face never under text.

Deck-level "image_heavy": true + "photo_pool": [photo, ...] gives every points/steps/compare/stats slide
without its own "photo" a face-aware photo band from the pool (round robin); "photo": false opts a slide out.
"shot" slides accept "frame": false for images that already carry their own device frame.

`photo` on a content slide = a full-width photo band under the content ("src" string, or
{"src", "caption"}). Every photo is face-aware: OpenCV finds the largest frontal face and the crop
keeps it inside the frame (cover photos put the face in the top third, and the text block only
starts below 54% of the slide, so text never sits on the face). Pass "face": [x,y,w,h] in source
pixels to override detection for a specific slide.

Title fragments: [["Writing code is", "dark"], ["only part of the job", "accent"|"hand"]].
Inline markup in any text: **bold**, __handwritten__, ==accent==, `code`. URLs and e-mail
addresses in any text become real PDF links; the author chip, footer brand, CTA button, QR and
social pills are links too (LinkedIn's document viewer keeps PDF link annotations clickable).

Design: mobile-first type (LinkedIn carousels are read on a ~400px-wide phone, so body text is
30px+ on the 1080px canvas), bodies that flex to fill the slide, sticky-note / tape decorations,
a browser frame for screenshots, and the author chip + handwritten slide number on every slide.
Photos are re-encoded to JPEG at <=1200px before embedding, so a 12-slide deck stays around 2-5 MB.
"""
from __future__ import annotations
import hashlib
import html
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets" / "carousel"
DECKS_OUT = ASSETS / "decks"             # html + previews (build artefacts, gitignored)
PDF_OUT = ROOT / "assets" / "carousels"   # final PDFs (committed; the queue posts these)
FONTS = ASSETS / "fonts"
CASCADE = ASSETS / "models" / "haarcascade_frontalface_default.xml"
try:
    from ..util import find_chrome
except ImportError:  # run as a plain script
    sys.path.insert(0, str(ROOT))
    from brand_engine.util import find_chrome
CHROME = find_chrome()

def _get_author_and_socials():
    try:
        from ..paths import load_config
        cfg = load_config()
        p = cfg.get("person", {})
        links = p.get("links", {})
        name = p.get("name", "Author")
        handle = p.get("handle", "")
        site = links.get("website") or ""
        profile_url = next((links[k] for k in ("instagram", "linkedin", "threads", "youtube", "tiktok", "x", "website")
                            if links.get(k)), "")
        avatar_rel = p.get("avatar") or "assets/me/avatar.jpg"
        avatar_path = ROOT / avatar_rel if not Path(avatar_rel).is_absolute() else Path(avatar_rel)
        if not avatar_path.exists():
            avatar_path = ASSETS / "avatar-placeholder.jpg"
        author = {
            "name": name,
            "handle": handle,
            "avatar": str(avatar_path),
            "site": site.replace("https://", "").replace("http://", "").rstrip("/"),
            "profile_url": profile_url,
        }
        labels = {"instagram": "Instagram", "linkedin": "LinkedIn", "threads": "Threads", "youtube": "YouTube",
                  "tiktok": "TikTok", "x": "X", "bluesky": "Bluesky", "github": "GitHub", "devto": "Dev.to"}
        socials = [(f"{label} · {handle or name}", links[k]) for k, label in labels.items() if links.get(k)]
        return author, socials
    except Exception:
        return {"name": "Author", "handle": "", "avatar": str(ASSETS / "avatar-placeholder.jpg"), "site": "", "profile_url": ""}, []

AUTHOR, SOCIALS = _get_author_and_socials()

THEMES = {
    "violet": dict(paper="#F6F2EA", grid="rgba(90,70,160,.11)", ink="#1B1830", muted="#5E5A73", accent="#5B4BD6",
                   soft="#E9E4FF", note="#FFF3B0", note2="#DDF3FF", pop="#F5B335"),
    "sky":    dict(paper="#E6EFFB", grid="rgba(30,80,170,.13)", ink="#14213D", muted="#4E5A73", accent="#1F5BD8",
                   soft="#D6E4FF", note="#FFF6C2", note2="#FFE1E1", pop="#FF7A59"),
    "cream":  dict(paper="#FBF4E8", grid="rgba(160,90,40,.11)", ink="#231A14", muted="#6B5A4E", accent="#C9401F",
                   soft="#FFE3D6", note="#FFF1C9", note2="#E3F4EA", pop="#2B7A78"),
    "mint":   dict(paper="#EAF6EF", grid="rgba(20,110,80,.13)", ink="#10241C", muted="#4F6A5F", accent="#0F7B5F",
                   soft="#D6F0E3", note="#FFF1C9", note2="#FFE6E0", pop="#F5B335"),
    "ink":    dict(paper="#F3F1EC", grid="rgba(0,0,0,.09)", ink="#111111", muted="#55555F", accent="#111111",
                   soft="#E6E3DC", note="#FFF3B0", note2="#DDEBFF", pop="#F5B335"),
    "rose":   dict(paper="#FBF0F2", grid="rgba(170,40,80,.10)", ink="#2A1420", muted="#6E5460", accent="#C2185B",
                   soft="#FFDDE6", note="#FFF3B0", note2="#E0F2FF", pop="#F5B335"),
    "tensor_dark": dict(paper="#0A0D14", grid="rgba(255,255,255,.05)", ink="#FFFFFF", muted="#94A3B8", accent="#00F5FF",
                        soft="#161B26", note="#131B2E", note2="#111827", pop="#10B981"),
    "tensor_clean": dict(paper="#FAFAFA", grid="rgba(0,0,0,.04)", ink="#090A0C", muted="#52525B", accent="#2563EB",
                         soft="#F1F5F9", note="#FFFFFF", note2="#F8FAFC", pop="#10B981"),
    "tensor_editorial": dict(paper="#FFFFFF", grid="transparent", ink="#0F0F10", muted="#55555A", accent="#E05638",
                            soft="#F4EAE0", note="#FFFFFF", note2="#FBF7F2", pop="#E05638"),
}


# ----------------------------------------------------------------------------- helpers
def furl(p: str | Path) -> str:
    p = Path(p)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve().as_uri()


def esc(s: str) -> str:
    return html.escape(str(s), quote=False)


def attr(s: str) -> str:
    return html.escape(str(s), quote=True)


def href(u: str) -> str:
    u = u.strip()
    if "@" in u and not u.startswith(("http://", "https://", "mailto:")):
        return "mailto:" + u
    return u if u.startswith(("http://", "https://", "mailto:")) else "https://" + u


_EMAIL = re.compile(r"(?<![\w.])([\w.+-]+@[\w-]+\.[\w.-]+\w)")
_URL = re.compile(r"(?<![\w@/.=\"'`-])((?:https?://)?(?:[a-z0-9-]+\.)+(?:in|com|dev|social|app|net|org|io|ai)\b(?:/[^\s<)\]\"',`]*[^\s<)\]\"',.:`])?)", re.I)


def linkify(s: str) -> str:
    """Turn e-mail addresses and URL-looking tokens into <a> links (input is already HTML-escaped)."""
    s = _EMAIL.sub(lambda m: f'<a class="lnk" href="mailto:{m.group(1)}">{m.group(1)}</a>', s)
    def repl(m):
        u = m.group(1)
        if u.lower().startswith("mailto:") or "@" in u:
            return u
        return f'<a class="lnk" href="{href(u)}">{u}</a>'
    return _URL.sub(repl, s)


def rich(s: str) -> str:
    """**bold**, __hand__, ==accent==, `code` inline markup + auto-linked URLs; everything else escaped."""
    s = linkify(esc(s))
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"~~(.+?)~~", r"\1", s)
    s = re.sub(r"__(.+?)__", r'<span class="hand">\1</span>', s)
    s = re.sub(r"==(.+?)==", r'<span class="acc">\1</span>', s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


def title_html(frags, tag="h2", cls="title") -> str:
    parts = []
    for text, style in frags:
        c = {"dark": "t-dark", "accent": "t-acc", "hand": "t-hand", "soft": "t-soft"}.get(style, "t-dark")
        parts.append(f'<span class="{c}">{rich(text)}</span>')
    return f'<{tag} class="{cls}">' + "<br>".join(parts) + f"</{tag}>"


def _src(src: str | Path) -> Path:
    p = Path(src)
    return p if p.is_absolute() else ROOT / p


def optimized(src: str | Path, out_dir: Path, max_w: int = 1200, keep_alpha: bool = False) -> Path:
    """Re-encode an image as a compact JPEG (or a downsized PNG if it needs transparency)."""
    from PIL import Image
    src = _src(src)
    out_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{src}|{src.stat().st_mtime_ns}|{max_w}|{keep_alpha}".encode()).hexdigest()[:12]
    im = Image.open(src)
    has_alpha = keep_alpha and im.mode in ("RGBA", "LA")
    dest = out_dir / f"{src.stem}-{key}.{'png' if has_alpha else 'jpg'}"
    if dest.exists():
        return dest
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    if has_alpha:
        im.save(dest, "PNG", optimize=True)
    else:
        im.convert("RGB").save(dest, "JPEG", quality=84, optimize=True, progressive=True)
    return dest


# ----------------------------------------------------------------------------- face-aware crops
_CASCADE = None
_FACE_CACHE: dict[str, tuple | None] = {}


def detect_face(src: Path) -> tuple[float, float, float] | None:
    """Largest frontal face as (cx, cy, size) in source pixels, or None when nothing is found."""
    global _CASCADE
    k = str(src)
    if k in _FACE_CACHE:
        return _FACE_CACHE[k]
    face = None
    try:
        import cv2
        import numpy as np
        from PIL import Image
        if _CASCADE is None and CASCADE.exists():
            _CASCADE = cv2.CascadeClassifier(str(CASCADE))
        if _CASCADE is not None and not _CASCADE.empty():
            im = np.array(Image.open(src).convert("L"))     # PIL decode: handles webp/alpha and unicode paths
            h, w = im.shape[:2]
            faces = _CASCADE.detectMultiScale(im, scaleFactor=1.08, minNeighbors=5, minSize=(max(24, int(w * 0.06)),) * 2)
            if len(faces):
                x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                face = (x + fw / 2, y + fh / 2, float(max(fw, fh)))
    except Exception as e:  # noqa: BLE001
        print("  (face detection skipped:", str(e)[:60], ")")
    _FACE_CACHE[k] = face
    return face


def crop_box(src: Path, W: int, H: int, face=None, focus: str | None = None, face_y: float = 0.42):
    """The WxH-aspect crop window of `src` as (left, top, cw, ch, f); f = (cx, cy, size) face in source px or None."""
    from PIL import Image
    iw, ih = Image.open(src).size
    ar = W / H
    if iw / ih > ar:
        ch = ih; cw = ch * ar
    else:
        cw = iw; ch = cw / ar
    f = None
    if face:
        x, y, fw, fh = face
        f = (x + fw / 2, y + fh / 2, float(max(fw, fh)))
    elif focus is None:
        f = detect_face(src)
    if f:
        cx, cy, fs = f
        # a face smaller than ~13% of the crop is unreadable on a phone: zoom in (never below 55% of the target size)
        if fs < 0.13 * ch:
            ch2 = max(min(fs / 0.2, ch), min(ch, H * 0.55))
            cw2 = ch2 * ar
            if cw2 <= iw and ch2 <= ih:
                ch, cw = ch2, cw2
        left, top = cx - cw / 2, cy - ch * face_y
    elif focus == "center":
        left, top = (iw - cw) / 2, (ih - ch) / 2
    else:  # "top" (and the no-face default): faces are almost always in the upper part of a photo
        left, top = (iw - cw) / 2, (ih - ch) * 0.12
    left = min(max(left, 0), iw - cw)
    top = min(max(top, 0), ih - ch)
    return left, top, cw, ch, f


def face_span(src: str | Path, W: int, H: int, face=None, face_y: float = 0.42) -> tuple[float, float] | None:
    """Vertical extent of the face inside the WxH crop as (top, bottom) fractions of the crop height (with a
    30% margin for hair and chin), or None when no face is known. Used to decide whether text may go below."""
    left, top, cw, ch, f = crop_box(_src(src), W, H, face, None, face_y)
    if not f:
        return None
    cx, cy, fs = f
    c = (cy - top) / ch
    half = fs * 0.5 * 1.3 / ch
    return (c - half, c + half)


def face_crop(src: str | Path, out_dir: Path, W: int, H: int, face=None, focus: str | None = None,
              face_y: float = 0.42, quality: int = 86) -> Path:
    """Crop `src` to exactly WxH so the (detected or given) face stays in frame.

    face   : optional [x, y, w, h] in source pixels (overrides detection)
    focus  : "top" | "center" fallback when no face is known
    face_y : where the face centre lands, as a fraction of the crop height (0.28 = top third)
    """
    from PIL import Image
    src = _src(src)
    out_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{src}|{src.stat().st_mtime_ns}|{W}x{H}|{face}|{focus}|{face_y}".encode()).hexdigest()[:12]
    dest = out_dir / f"{src.stem}-fc{W}x{H}-{key}.jpg"
    if dest.exists():
        return dest
    left, top, cw, ch, _f = crop_box(src, W, H, face, focus, face_y)
    im = Image.open(src).convert("RGB")
    im = im.crop((round(left), round(top), round(left + cw), round(top + ch))).resize((W, H), Image.LANCZOS)
    im.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)
    return dest


def photo_spec(p):
    """Normalise a slide's `photo` field to (src, caption, face)."""
    if isinstance(p, str):
        return p, "", None
    return p["src"], p.get("caption", ""), p.get("face")


# ----------------------------------------------------------------------------- CSS
def css(theme: dict) -> str:
    f = {k: furl(FONTS / v) for k, v in {
        "caveat": "Caveat[wght].ttf", "patrick": "PatrickHand-Regular.ttf", "inter": "Inter[opsz,wght].ttf",
        "pop400": "Poppins-Regular.ttf", "pop500": "Poppins-Medium.ttf", "pop600": "Poppins-SemiBold.ttf",
        "pop700": "Poppins-Bold.ttf", "pop800": "Poppins-ExtraBold.ttf", "fraunces": "Fraunces[SOFT,WONK,opsz,wght].ttf",
    }.items()}
    t = theme
    return f"""
@font-face{{font-family:Caveat;src:url("{f['caveat']}");font-weight:400 700}}
@font-face{{font-family:Patrick;src:url("{f['patrick']}")}}
@font-face{{font-family:Inter;src:url("{f['inter']}");font-weight:100 900}}
@font-face{{font-family:Poppins;src:url("{f['pop400']}");font-weight:400}}
@font-face{{font-family:Poppins;src:url("{f['pop500']}");font-weight:500}}
@font-face{{font-family:Poppins;src:url("{f['pop600']}");font-weight:600}}
@font-face{{font-family:Poppins;src:url("{f['pop700']}");font-weight:700}}
@font-face{{font-family:Poppins;src:url("{f['pop800']}");font-weight:800}}
@font-face{{font-family:Fraunces;src:url("{f['fraunces']}");font-weight:300 900}}
@page{{size:1080px 1350px;margin:0}}
*{{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
html,body{{margin:0;padding:0;background:#fff}}
a{{color:inherit;text-decoration:none}}
a.lnk{{text-decoration:underline;text-decoration-style:dotted;text-decoration-color:var(--acc);text-decoration-thickness:2px;text-underline-offset:6px}}
:root{{--paper:{t['paper']};--grid:{t['grid']};--ink:{t['ink']};--muted:{t['muted']};--acc:{t['accent']};--soft:{t['soft']};
  --note:{t['note']};--note2:{t['note2']};--pop:{t['pop']}}}
.slide{{position:relative;width:1080px;height:1350px;overflow:hidden;page-break-after:always;break-after:page;background:var(--paper);
  font-family:Inter,system-ui,sans-serif;color:var(--ink)}}
.slide:last-child{{page-break-after:auto;break-after:auto}}
.grid{{position:absolute;inset:0;background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);
  background-size:54px 54px;mask-image:radial-gradient(ellipse at 50% 45%,#000 50%,transparent 100%);-webkit-mask-image:radial-gradient(ellipse at 50% 45%,#000 50%,transparent 100%)}}
.noise{{position:absolute;inset:0;opacity:.5;background:radial-gradient(circle at 12% 18%,rgba(255,255,255,.75),transparent 42%),radial-gradient(circle at 90% 85%,rgba(0,0,0,.05),transparent 45%)}}
/* one quiet doodle per slide, never more */
.doo{{position:absolute;z-index:3;pointer-events:none}}
.doo.star{{width:34px;height:34px;color:var(--pop);font:800 34px/1 Poppins}}
.doo.dots{{width:96px;height:48px;background-image:radial-gradient(color-mix(in oklab,var(--acc) 55%,transparent) 3px,transparent 3.5px);background-size:16px 16px}}
/* chrome */
.chip{{position:absolute;left:64px;top:56px;display:flex;align-items:center;gap:16px;z-index:6}}
.chip img{{width:70px;height:70px;border-radius:50%;object-fit:cover;border:3px solid #fff;box-shadow:0 4px 14px rgba(0,0,0,.14);outline:3px solid var(--acc);outline-offset:2px}}
.chip b{{display:block;font:700 26px/1.1 Poppins;color:var(--ink)}}
.chip span{{display:block;font:500 18px/1.3 Inter;color:var(--muted);margin-top:4px}}
.num{{position:absolute;right:64px;top:30px;font:700 124px/1 Caveat;color:var(--acc);z-index:6;letter-spacing:-2px}}
.foot{{position:absolute;left:64px;right:64px;bottom:40px;display:flex;justify-content:space-between;align-items:center;font:600 20px Inter;color:var(--muted);z-index:6}}
.foot .brand{{display:flex;align-items:center;gap:10px}}
.foot .dot{{width:11px;height:11px;border-radius:50%;background:var(--acc)}}
.foot .swipe{{font:700 30px Caveat;color:var(--acc)}}
/* body: a flex column that fills the slide so nothing pools at the top */
.body{{position:absolute;left:64px;right:64px;top:176px;bottom:104px;z-index:5;display:flex;flex-direction:column;gap:22px}}
.grow{{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}}
.title{{margin:0;font:800 68px/1.06 Poppins;letter-spacing:-1.8px}}
.title .t-dark{{color:var(--ink)}} .title .t-acc{{color:var(--acc)}} .title .t-soft{{color:var(--muted);font-weight:600}}
.title .t-hand{{font:700 78px/1 Caveat;color:var(--acc)}}
.hand{{font:700 1.15em Caveat;color:var(--acc)}}
.acc{{color:var(--acc);font-weight:700}}
code{{font:600 .86em ui-monospace,Consolas,monospace;background:var(--soft);border-radius:8px;padding:2px 10px;color:var(--ink)}}
.intro{{font:500 30px/1.4 Inter;color:var(--muted);margin:0;max-width:920px}}
.card{{position:relative;background:#fff;border-radius:24px;padding:36px 40px;box-shadow:0 16px 44px rgba(20,20,40,.11),0 1px 0 rgba(0,0,0,.05)}}
.card.note{{background:var(--note)}} .card.note2{{background:var(--note2)}} .card.soft{{background:var(--soft)}}
.tape{{position:absolute;width:160px;height:40px;background:rgba(255,255,255,.62);border:1px solid rgba(0,0,0,.05);box-shadow:0 2px 6px rgba(0,0,0,.08);z-index:2}}
.tape.tl{{left:-34px;top:-18px;transform:rotate(-8deg)}} .tape.tr{{right:-34px;top:-18px;transform:rotate(7deg)}}
.tape.pop{{background:color-mix(in oklab,var(--pop) 55%,#fff)}}
.rot-l{{transform:rotate(-1.4deg)}} .rot-r{{transform:rotate(1.3deg)}}
ul.pts{{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:20px}}
ul.pts li{{display:flex;gap:20px;align-items:flex-start;font:500 30px/1.36 Inter;color:var(--ink)}}
ul.pts .ic{{flex:0 0 52px;height:52px;border-radius:15px;background:var(--acc);color:#fff;display:flex;align-items:center;justify-content:center;font:800 26px Poppins;margin-top:1px}}
ul.pts .ic.check::before{{content:"✓"}}
ul.pts.compact li{{font-size:27px;line-height:1.32;gap:16px}} ul.pts.compact .ic{{flex-basis:44px;height:44px;font-size:22px;border-radius:12px}}
.rule{{margin-top:auto;background:var(--soft);border-radius:20px;padding:24px 30px;display:flex;gap:20px;align-items:center;font:600 27px/1.35 Inter;color:var(--ink)}}
.rule .lbl{{flex:0 0 auto;background:var(--acc);color:#fff;border-radius:11px;padding:9px 18px;font:700 21px Poppins;letter-spacing:.3px}}
.sticker{{position:absolute;right:26px;top:-22px;font:700 34px Caveat;color:#fff;background:var(--acc);padding:6px 18px;border-radius:14px;transform:rotate(5deg);z-index:3;box-shadow:0 8px 20px rgba(0,0,0,.15)}}
/* photo band under the content of a slide */
/* the caption sits in a white strip UNDER the photo, never on it */
.band{{position:relative;flex:0 1 auto;height:330px;min-height:160px;border-radius:26px;overflow:hidden;box-shadow:0 18px 44px rgba(20,20,40,.16);border:6px solid #fff;margin-top:auto;display:flex;flex-direction:column;background:#fff}}
.band.short{{height:270px}}
.band img{{display:block;width:100%;flex:1 1 auto;min-height:0;object-fit:cover}}
.band .cap{{flex:0 0 auto;height:58px;display:flex;align-items:center;background:#fff;color:var(--ink);padding:0 20px;font:600 22px/1.2 Inter}}
.band .cap span{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.band .cap b{{color:var(--acc)}}
.band.pol{{display:flex;flex-direction:row;border:0;box-shadow:none;overflow:visible;background:transparent;gap:26px;align-items:stretch}}
.band.pol img{{flex:0 0 auto;width:330px;height:330px;border-radius:26px;border:6px solid #fff;box-shadow:0 18px 44px rgba(20,20,40,.16);transform:rotate(1.5deg)}}
.band.pol.short img{{width:270px;height:270px}}
.band.pol .pcap{{flex:1;background:var(--soft);border-radius:24px;padding:28px 34px;font:700 42px/1.15 Caveat;color:var(--ink);display:flex;align-items:center}}
.band.pol .pcap b{{color:var(--acc)}}
/* compare */
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:28px;align-items:stretch}}
.cols>div{{display:flex;flex-direction:column}}
.cols .lbl{{display:inline-block;align-self:flex-start;font:700 24px Poppins;color:var(--ink);background:#fff;border:2.5px solid var(--ink);border-radius:12px;padding:10px 18px;margin-bottom:18px}}
.cols .lbl.good{{background:var(--acc);border-color:var(--acc);color:#fff}}
.cols .card{{flex:1}}
.bubble{{position:relative;background:#fff;border:3px solid var(--ink);border-radius:24px;padding:34px 34px;font:600 31px/1.4 Inter;flex:1;display:flex;align-items:center;max-height:640px}}
.bubble::after{{content:"";position:absolute;left:48px;bottom:-24px;border:13px solid transparent;border-top-color:var(--ink)}}
.bubble.hand{{font:700 46px/1.22 Caveat;color:var(--ink)}}
.cols ul{{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:18px;font:500 28px/1.36 Inter}}
.cols ul li{{display:flex;gap:14px}} .cols ul li::before{{content:"—";color:var(--acc);font-weight:800;flex:0 0 auto}}
.cols .bad ul li::before{{content:"✕";color:#D14343}}
/* stats */
.tiles{{display:grid;grid-template-columns:repeat(2,1fr);gap:26px;flex:1}}
.tiles.three{{grid-template-columns:repeat(3,1fr)}}
.tile{{background:#fff;border-radius:24px;padding:34px 30px 30px;box-shadow:0 14px 38px rgba(20,20,40,.10);display:flex;flex-direction:column;justify-content:flex-start;position:relative;overflow:hidden}}
.tile::after{{content:"";position:absolute;right:-30px;bottom:-30px;width:120px;height:120px;border-radius:50%;background:var(--soft)}}
.tile .v{{font:800 92px/1 Poppins;color:var(--acc);letter-spacing:-3px}}
.tile .l{{font:600 25px/1.32 Inter;color:var(--muted);margin-top:14px;position:relative;z-index:1}}
.tiles.withband .tile .v{{font-size:76px}} .tiles.withband .tile{{padding:28px 28px 24px}}
/* browser frame */
.browser{{background:#fff;border-radius:24px;overflow:hidden;box-shadow:0 20px 54px rgba(20,20,40,.17);border:1px solid rgba(0,0,0,.06);display:flex;flex-direction:column;position:relative}}
.browser .bar{{height:54px;background:#F1EFEA;display:flex;align-items:center;gap:10px;padding:0 20px;border-bottom:1px solid rgba(0,0,0,.06);flex:0 0 auto}}
.browser .bar i{{width:14px;height:14px;border-radius:50%;display:inline-block}}
.browser .bar i:nth-child(1){{background:#FF5F57}} .browser .bar i:nth-child(2){{background:#FEBC2E}} .browser .bar i:nth-child(3){{background:#28C840}}
.browser .url{{margin-left:12px;flex:1;background:#fff;border-radius:9px;height:34px;display:flex;align-items:center;padding:0 14px;font:600 18px Inter;color:var(--muted)}}
.browser img{{display:block;width:100%;height:100%;object-fit:cover;object-position:top;flex:1 1 auto;min-height:0}}
.caption{{font:500 27px/1.4 Inter;color:var(--muted);margin:0}}
.plain{{border-radius:24px;overflow:hidden;box-shadow:0 20px 54px rgba(20,20,40,.17);display:flex;position:relative;background:#fff;border:6px solid #fff}}
.plain img{{display:block;width:100%;height:100%;object-fit:cover;object-position:top;flex:1 1 auto;min-height:0}}
/* photo slide: full-bleed (text in the bottom 40%, white on a shade) or panel (700px photo, text on paper) */
.pho .bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:1}}
.pho.full .shade{{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.14) 0%,rgba(0,0,0,.08) 30%,rgba(0,0,0,.66) 54%,rgba(0,0,0,.92) 100%);z-index:2}}
.pho .ptext{{position:absolute;left:64px;right:64px;z-index:6;display:flex;flex-direction:column;gap:20px}}
.pho.full .ptext{{bottom:120px;max-height:560px;justify-content:flex-end}}
.pho.full .title{{font-size:64px}} .pho.full .title .t-dark{{color:#fff}} .pho.full .title .t-acc,.pho.full .title .t-hand{{color:var(--pop)}}
.pho.full .intro,.pho.full .plines{{color:#fff}}
.pho.full .chip b,.pho.full .foot{{color:#fff}} .pho.full .chip span{{color:rgba(255,255,255,.8)}} .pho.full .num,.pho.full .foot .swipe{{color:var(--pop)}}
.pho.full .grid,.pho.full .noise,.pho.full .doo{{display:none}}
.pho .plines{{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:14px;font:500 29px/1.36 Inter}}
.pho .plines li{{display:flex;gap:16px}} .pho .plines li::before{{content:"→";color:var(--pop);font-weight:800;flex:0 0 auto}}
.pho .pcap{{align-self:flex-start;background:rgba(255,255,255,.92);color:var(--ink);border-radius:12px;padding:9px 16px;font:600 21px Inter}}
.pho.panel .ppanel{{position:absolute;left:0;top:0;width:1080px;height:700px;overflow:hidden;z-index:1}}
.pho.panel .ppanel img{{display:block;width:100%;height:100%;object-fit:cover}}
.pho.panel .ppanel::after{{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.22),transparent 24%,transparent 80%,var(--paper) 100%)}}
.pho.panel .chip{{background:rgba(255,255,255,.9);padding:8px 22px 8px 8px;border-radius:999px;box-shadow:0 8px 24px rgba(0,0,0,.14)}}
.pho.panel .num{{color:#fff;text-shadow:0 4px 18px rgba(0,0,0,.35)}}
.pho.panel .ptext{{top:724px;bottom:104px;justify-content:center;gap:16px}}
.pho.panel .title{{font-size:54px;letter-spacing:-1.2px}} .pho.panel .title .t-hand{{font-size:62px}}
.pho.panel .plines{{font-size:27px}} .pho.panel .plines li::before{{color:var(--acc)}}
.pho.panel .pcap{{background:var(--soft)}}
/* steps */
.steps{{display:flex;flex-direction:column;position:relative;flex:1;justify-content:space-around}}
.step{{display:grid;grid-template-columns:76px 1fr;gap:24px;padding:12px 0;position:relative}}
.step .n{{width:64px;height:64px;border-radius:50%;background:var(--acc);color:#fff;display:flex;align-items:center;justify-content:center;font:800 28px Poppins}}
.step:not(:last-child)::after{{content:"";position:absolute;left:31px;top:82px;bottom:-8px;border-left:3px dashed color-mix(in oklab,var(--acc) 45%,transparent)}}
.step h4{{margin:10px 0 6px;font:700 32px/1.15 Poppins;color:var(--ink)}}
.step p{{margin:0;font:500 26px/1.38 Inter;color:var(--muted)}}
.withband .step{{padding:6px 0}} .withband .step h4{{font-size:29px;margin:8px 0 4px}} .withband .step p{{font-size:24px}}
/* quote */
.quote{{font:700 60px/1.2 Caveat;color:var(--ink);margin:0}}
.by{{font:600 26px Inter;color:var(--muted);margin-top:28px}}
/* cover (shared) */
.cover .big{{position:absolute;left:64px;right:64px;top:170px;z-index:6}}
.cover .kicker{{display:inline-block;background:var(--acc);color:#fff;font:700 23px Poppins;letter-spacing:1.5px;text-transform:uppercase;border-radius:12px;padding:13px 22px;margin-bottom:28px;position:relative}}
.cover .title{{font-size:88px;line-height:1.02;margin:0 0 28px;position:relative;z-index:7}}
.cover .title .t-hand{{font-size:100px}}
.cover .sub{{font:500 31px/1.4 Inter;color:var(--muted);max-width:720px}}
.cover .swipe-big{{position:absolute;left:64px;bottom:64px;font:700 38px Caveat;color:var(--acc);z-index:6;display:flex;align-items:center;gap:12px}}
.cover .swipe-big .pill{{font:700 22px Poppins;background:var(--ink);color:#fff;border-radius:999px;padding:8px 16px}}
/* cover: cutout mode (text column left, cutout right; title kept to left 470px so it never crosses the cutout) */
.cover.cutout .cut{{position:absolute;right:-30px;bottom:0px;height:880px;max-width:540px;object-fit:contain;object-position:right bottom;z-index:4;filter:drop-shadow(0 30px 40px rgba(0,0,0,.25))}}
.cover.cutout .big{{position:absolute;left:64px;top:170px;max-width:470px;z-index:6}}
.cover.cutout .title{{max-width:470px;font-size:72px;line-height:1.02;margin:0 0 24px;word-break:break-word}}
.cover.cutout .sub{{max-width:470px}}
.cover.cutout .blob{{position:absolute;right:-180px;bottom:-300px;width:980px;height:980px;border-radius:50%;background:var(--soft);z-index:2}}
.cover.cutout .blob2{{position:absolute;right:120px;bottom:-40px;width:520px;height:520px;border-radius:50%;background:color-mix(in oklab,var(--pop) 35%,var(--paper));z-index:2}}
/* cover: full-bleed photo mode; the face-aware crop puts the face in the top third, the text block starts at 54% */
.cover.photo-mode .photo{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:1}}
.cover.photo-mode .shade{{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.10) 0%,rgba(0,0,0,.10) 34%,rgba(0,0,0,.62) 56%,rgba(0,0,0,.90) 100%);z-index:2}}
.cover.photo-mode .big{{top:auto;bottom:170px;max-height:600px;display:flex;flex-direction:column;justify-content:flex-end}}
.cover.photo-mode .title{{font-size:80px}} .cover.photo-mode .title .t-hand{{font-size:92px}}
.cover.photo-mode .title .t-dark,.cover.photo-mode .sub,.cover.photo-mode .chip b{{color:#fff}}
.cover.photo-mode .chip span{{color:rgba(255,255,255,.8)}}
.cover.photo-mode .title .t-acc,.cover.photo-mode .title .t-hand{{color:var(--pop)}}
.cover.photo-mode .swipe-big{{color:var(--pop)}}
/* cover: split mode (photo panel on top, text panel below) */
.cover.split .pwrap{{position:absolute;left:0;top:0;width:1080px;height:760px;overflow:hidden;z-index:1}}
.cover.split .pwrap img{{display:block;width:100%;height:100%;object-fit:cover}}
.cover.split .pwrap::after{{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.22),transparent 26%,transparent 78%,var(--paper) 100%)}}
.cover.split .chip{{background:rgba(255,255,255,.88);padding:8px 22px 8px 8px;border-radius:999px;box-shadow:0 8px 24px rgba(0,0,0,.14)}}
.cover.split .big{{top:780px;bottom:124px;overflow:hidden}}
.cover.split .title.long{{font-size:60px}} .cover.split .title.long .t-hand{{font-size:70px}} .cover.split .title.long+.sub{{font-size:26px}}
.cover.split .kicker{{margin-bottom:20px;padding:11px 18px;font-size:21px}}
.cover.split .title{{font-size:72px;line-height:1.04;margin-bottom:20px}} .cover.split .title .t-hand{{font-size:84px}}
.cover.split .sub{{font-size:28px;max-width:820px}}
.cover.chip-r .chip,.pho.chip-r .chip{{left:auto;right:64px;flex-direction:row-reverse;text-align:right}}
.pho.chip-r .num{{right:auto;left:64px}}
/* gallery */
.gal{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;flex:1;align-content:start}}
.gal figure{{margin:0;background:#fff;padding:10px 10px 12px;border-radius:14px;box-shadow:0 12px 28px rgba(0,0,0,.13)}}
.gal img{{width:100%;height:270px;object-fit:cover;border-radius:8px;display:block}}
.gal figcaption{{font:600 19px/1.25 Inter;color:var(--muted);margin-top:10px;text-align:center}}
.gal.two{{grid-template-columns:repeat(2,1fr)}} .gal.two img{{height:400px}}
/* cta */
.cta .head{{font:800 70px/1.06 Poppins;letter-spacing:-1.8px;margin:0;max-width:620px}}
.cta .urlpill{{display:inline-flex;align-self:flex-start;align-items:center;gap:14px;background:var(--ink);color:#fff;border-radius:18px;padding:20px 30px;font:700 38px Poppins;max-width:600px;word-break:break-all;line-height:1.15}}
.cta .urlpill.long{{font-size:29px}} .cta .urlpill.xlong{{font-size:24px}}
.cta .lines{{display:flex;flex-direction:column;gap:18px;font:500 28px/1.4 Inter;color:var(--ink);margin:0;padding:0;max-width:640px}}
.cta .lines li{{list-style:none}}
.cta .soc{{display:flex;flex-wrap:wrap;gap:12px;max-width:640px}}
.cta .soc a{{background:#fff;border:2px solid var(--soft);border-radius:999px;padding:11px 18px;font:600 20px Inter;color:var(--ink)}}
.cta .qr{{position:absolute;right:64px;bottom:120px;background:#fff;padding:18px;border-radius:20px;box-shadow:0 14px 38px rgba(0,0,0,.13);z-index:6;display:block}}
.cta .qr img{{width:230px;height:230px;display:block}}
.cta .qr small{{display:block;text-align:center;font:600 18px Inter;color:var(--muted);margin-top:10px}}
.cta .portrait{{position:absolute;right:64px;top:190px;width:320px;height:320px;border-radius:50%;object-fit:cover;border:8px solid #fff;box-shadow:0 18px 44px rgba(0,0,0,.18);outline:5px solid var(--acc);outline-offset:4px;z-index:6}}
del.strike{{text-decoration:none !important}}

/* Tensor Editorial Layout (Exact Tensor Boy Front Page & Styling) */
body.tensor_editorial {{ background: #FFFFFF !important; }}
body.tensor_editorial .grid,
body.tensor_editorial .noise,
body.tensor_editorial .doo,
body.tensor_editorial .tape,
body.tensor_editorial .sticker {{ display: none !important; }}
body.tensor_editorial .rot-l,
body.tensor_editorial .rot-r {{ transform: none !important; }}

/* Chrome / Top bar */
body.tensor_editorial .chip {{
    left: 72px; top: 56px;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    z-index: 10;
}}
body.tensor_editorial .chip img {{ display: none !important; }}
body.tensor_editorial .chip div {{ display: block; }}
body.tensor_editorial .chip b {{
    font: 500 24px/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
    color: #4A4A4A !important;
    letter-spacing: -0.5px;
}}
body.tensor_editorial .chip span {{ display: none !important; }}
body.tensor_editorial .num {{
    font: 700 26px/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
    color: var(--acc) !important;
    top: 56px; right: 72px;
    letter-spacing: 0;
}}

/* Cover Slide */
body.tensor_editorial .cover.cutout {{
    background: #FFFFFF !important;
    overflow: hidden;
}}
body.tensor_editorial .cover.cutout .big {{
    top: 230px; left: 72px;
    max-width: 500px;
    z-index: 7;
}}
body.tensor_editorial .cover.cutout .title {{
    font: 900 60px/1.04 Poppins, Inter, sans-serif !important;
    letter-spacing: -1.8px;
    color: #111111 !important;
    text-transform: uppercase;
    margin-bottom: 24px;
    word-break: normal;
    overflow-wrap: normal;
    hyphens: none;
}}
body.tensor_editorial .cover.cutout .title del.strike {{
    text-decoration: none !important;
}}
body.tensor_editorial .cover.cutout .sub {{
    font: 700 30px/1.3 Inter, sans-serif !important;
    color: #111111 !important;
    max-width: 440px;
    margin-bottom: 18px;
}}
body.tensor_editorial .cover.cutout .sub .acc {{ color: #E05638; }}
body.tensor_editorial .cover.cutout .desc {{
    font: 400 21px/1.5 Inter, sans-serif !important;
    color: #666666 !important;
    max-width: 420px;
}}
body.tensor_editorial .cover.cutout .blob {{
    position: absolute;
    right: -130px; bottom: 120px;
    width: 860px; height: 860px;
    border-radius: 50%;
    background: #F4EAE0 !important;
    z-index: 2;
    box-shadow: none !important;
}}
body.tensor_editorial .cover.cutout .blob2 {{ display: none !important; }}
body.tensor_editorial .cover.cutout .cut {{
    position: absolute;
    right: -30px; bottom: 0px;
    height: 960px;
    max-width: 560px;
    object-fit: contain;
    object-position: right bottom;
    z-index: 4;
    filter: drop-shadow(0 20px 35px rgba(0,0,0,.08));
}}
body.tensor_editorial .cover .kicker {{ display: none !important; }}
body.tensor_editorial .cover .swipe-big {{
    left: 72px; bottom: 56px;
    font: 500 22px/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
    color: #666666 !important;
    display: flex; gap: 8px; align-items: center;
    z-index: 10;
}}
body.tensor_editorial .cover .swipe-big .pill {{ display: none !important; }}
body.tensor_editorial .cover-dots {{
    position: absolute;
    right: 72px; bottom: 60px;
    display: flex; gap: 8px; align-items: center;
    z-index: 10;
}}
body.tensor_editorial .cover-dots .dot {{
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #D8D4CE;
}}
body.tensor_editorial .cover-dots .dot.active {{
    background: #E05638;
    width: 10px; height: 10px;
}}

/* Inside Slides */
body.tensor_editorial .slide:not(.cover) {{
    background: #FFFFFF !important;
    padding: 120px 72px 100px 72px;
}}
body.tensor_editorial .slide:not(.cover) .title {{
    font: 800 50px/1.12 Poppins, Inter, sans-serif !important;
    letter-spacing: -1.6px;
    color: #111111;
    margin-bottom: 14px;
}}
body.tensor_editorial .slide:not(.cover) .intro {{
    font: 500 24px/1.45 Inter, sans-serif !important;
    color: #555555;
    margin-bottom: 24px;
}}
body.tensor_editorial .foot {{
    font: 500 20px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
    color: #777777;
    border-top: 1px solid #ECEBE8;
    padding-top: 18px;
    bottom: 36px;
    left: 72px; right: 72px;
}}
body.tensor_editorial .foot .swipe {{
    font: 600 20px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    color: #E05638;
}}
body.tensor_editorial .card {{
    background: #FAF9F6 !important;
    border: 1.5px solid #EBE8E2 !important;
    border-radius: 20px !important;
    box-shadow: 0 8px 24px rgba(0,0,0,.03) !important;
    padding: 30px 34px !important;
}}
body.tensor_editorial .card.note2 {{
    background: #F4EAE0 !important;
    border-color: #E6D8C9 !important;
}}
body.tensor_editorial .bad .lbl, body.tensor_editorial .good .lbl {{
    font: 700 18px Inter, sans-serif !important;
    letter-spacing: 0.5px !important;
    text-transform: uppercase !important;
    border-radius: 8px !important;
}}
body.tensor_editorial .pts li {{
    font: 500 24px/1.45 Inter, sans-serif;
    color: #1F1F1F;
}}
body.tensor_editorial .pts li .ic.check {{ background: #E05638 !important; }}
body.tensor_editorial .rule {{
    background: #FAF9F6 !important;
    border-left: 6px solid #E05638 !important;
    border-radius: 14px !important;
    box-shadow: none !important;
}}
body.tensor_editorial .rule .lbl {{
    background: #E05638 !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
}}
body.tensor_editorial .step .n {{
    background: #E05638 !important;
    color: #FFFFFF !important;
    font-weight: 800 !important;
}}

/* Universal Contrast Safeguards */
.card, .cols .card {{ color: var(--ink); }}
body.tensor_dark .card, body.tensor_dark .cols .card, body.tensor_dark .bubble {{
    background: #161B26 !important;
    color: #FFFFFF !important;
    border: 1.5px solid #334155 !important;
}}
body.tensor_dark .cols .lbl {{
    background: #161B26 !important;
    color: #FFFFFF !important;
    border: 2px solid #334155 !important;
}}
body.tensor_dark ul.pts li {{ color: #FFFFFF !important; }}
body.tensor_dark .cols ul li {{ color: #E2E8F0 !important; }}
body.tensor_dark .cols .lbl.good {{
    background: var(--acc) !important;
    color: #0A0D14 !important;
    border-color: var(--acc) !important;
}}
"""


# ----------------------------------------------------------------------------- slide builders
DOODLES = [
    '<div class="doo star" style="right:250px;top:64px">✦</div>',
    '<div class="doo dots" style="right:70px;bottom:130px"></div>',
    '<div class="doo star" style="right:96px;bottom:200px">✦</div>',
    '',
    '<div class="doo dots" style="left:64px;top:150px"></div>',
    '',
]


def chip_html(a: dict, avatar: Path) -> str:
    handle_disp = a.get("handle") or a.get("name") or ""
    return (f'<a class="chip" href="{attr(a.get("profile_url", AUTHOR["profile_url"]))}"><img src="{furl(avatar)}"><div><b>{esc(handle_disp)}</b>'
            f'<span>{esc(a.get("handle", ""))}</span></div></a>')


def chrome(n: int, total: int, author: dict, brand: str, avatar: Path) -> str:
    return (f'<div class="grid"></div><div class="noise"></div>{DOODLES[n % len(DOODLES)]}'
            f'{chip_html(author, avatar)}'
            f'<div class="num">{n:02d}</div>'
            f'<footer class="foot"><a class="brand" href="{attr(href(brand))}"><span class="dot"></span>{esc(brand)}</a>'
            f'<span class="swipe">{"swipe →" if n < total else "follow for more →"}</span></footer>')


def note_html(s, default_label):
    if not s.get("note"):
        return ""
    return f'<div class="rule"><span class="lbl">{esc(s.get("note_label", default_label))}</span><div>{rich(s["note"])}</div></div>'


def intro_html(s):
    return f'<p class="intro">{rich(s["intro"])}</p>' if s.get("intro") else ""


def _face_fits_band(src, face, W: int, H: int) -> bool:
    """False when the face is taller than ~70% of the band's crop window (a wide strip would slice it)."""
    from PIL import Image
    p = _src(src)
    iw, ih = Image.open(p).size
    ar = W / H
    ch = ih if iw / ih > ar else iw / ar
    f = (face[0] + face[2] / 2, face[1] + face[3] / 2, float(max(face[2], face[3]))) if face else detect_face(p)
    return not f or f[2] <= 0.7 * ch


def band_html(s, ctx, short=False) -> str:
    """Face-aware photo band under a content slide's main block.

    Wide strip by default; when the face would not fit a strip, a polaroid (square face crop on the
    right, caption card on the left) is used instead so the face is never sliced."""
    if not s.get("photo"):
        return ""
    src, cap, face = photo_spec(s["photo"])
    h = 270 if short else 330
    ih = h - 12 - (58 if cap else 0)          # 6px frame top+bottom, caption strip under the photo
    if _face_fits_band(src, face, 940, ih):
        img = face_crop(src, ctx["img"], 940, ih, face=face)
        cap_html = f'<div class="cap"><span>{rich(cap)}</span></div>' if cap else ""
        return f'<div class="band {"short" if short else ""}"><img src="{furl(img)}">{cap_html}</div>'
    img = face_crop(src, ctx["img"], h, h, face=face, face_y=0.45)
    cap_html = f'<div class="pcap"><span>{rich(cap)}</span></div>' if cap else '<div class="pcap"></div>'
    return f'<div class="band pol {"short" if short else ""}">{cap_html}<img src="{furl(img)}"></div>'


def s_cover(s, n, total, a, brand, ctx):
    mode = s.get("photo_mode", "cutout")
    extra = ""
    if mode == "photo":
        # text starts at ~46% of the slide: if the face (plus margin) would reach it, or no face is found,
        # use the split layout instead, where the text panel sits entirely below the photo
        span = face_span(s["photo"], 1080, 1350, s.get("face"), 0.27)
        if span is None or span[1] > 0.46 or span[0] < 0.10:
            mode = "split"
            print(f"  cover: face span {span and tuple(round(x, 2) for x in span)} -> split layout")
    if mode == "split":
        span = face_span(s["photo"], 1080, 760, s.get("face"), 0.44)
        if span is not None and span[0] < 0.18:      # face would touch the author chip: move the chip right
            extra = " chip-r"
    if mode == "photo":
        mode_cls = "photo-mode"
    elif mode == "split":
        mode_cls = "split"
    else:
        mode_cls = "cutout"
    out = [f'<section class="slide cover {mode_cls}{extra}">']
    if mode == "photo":
        img = face_crop(s["photo"], ctx["img"], 1080, 1350, face=s.get("face"), face_y=0.27)
        out.append(f'<img class="photo" src="{furl(img)}"><div class="shade"></div>')
    elif mode == "split":
        img = face_crop(s["photo"], ctx["img"], 1080, 760, face=s.get("face"), face_y=0.44)
        out.append(f'<div class="grid"></div><div class="pwrap"><img src="{furl(img)}"></div>')
    else:
        out.append('<div class="grid"></div><div class="noise"></div><div class="blob"></div><div class="blob2"></div>')
        if s.get("photo"):
            out.append(f'<img class="cut" src="{furl(optimized(s["photo"], ctx["img"], 1000, keep_alpha=True))}">')
    out.append(chip_html(a, ctx["avatar"]))
    out.append('<div class="big">')
    if s.get("kicker"):
        out.append(f'<div class="kicker"><div class="tape tl pop" style="width:90px;height:26px"></div>{esc(s["kicker"])}</div>')
    out.append(title_html(s["title"], "h1", "title long" if len(s["title"]) > 3 else "title"))
    if s.get("subtitle"):
        out.append(f'<p class="sub">{rich(s["subtitle"])}</p>')
    if s.get("desc"):
        out.append(f'<p class="desc">{rich(s["desc"])}</p>')
    out.append("</div>")
    out.append(f'<div class="swipe-big">swipe → <span class="pill">{total} slides</span></div>')
    dots = "".join('<span class="dot active"></span>' if i == 0 else '<span class="dot"></span>' for i in range(total))
    out.append(f'<div class="cover-dots">{dots}</div>')
    out.append("</section>")
    return "".join(out)


def s_points(s, n, total, a, brand, ctx):
    icon = s.get("icon", "check")
    compact = " compact" if sum(len(b) for b in s["bullets"]) > 520 or len(s["bullets"]) > 4 or s.get("photo") else ""
    lis = "".join(f'<li><span class="ic {"check" if icon == "check" else ""}">{"" if icon == "check" else esc(icon)}</span><div>{rich(b)}</div></li>'
                  for b in s["bullets"])
    sticker = f'<div class="sticker">{esc(s["sticker"])}</div>' if s.get("sticker") else ""
    short = bool(s.get("note")) or sum(len(b) for b in s["bullets"]) > 420
    return (f'<section class="slide">{chrome(n, total, a, brand, ctx["avatar"])}<div class="body">{title_html(s["title"])}{intro_html(s)}'
            f'<div class="grow"><div class="card {s.get("card", "")}" style="flex:0 0 auto">{sticker}<div class="tape tl"></div><ul class="pts{compact}">{lis}</ul></div>'
            f'{band_html(s, ctx, short)}</div>{note_html(s, "Takeaway")}</div></section>')


def s_compare(s, n, total, a, brand, ctx):
    def col(c, good):
        lbl = f'<div class="lbl {"good" if good else ""}">{esc(c["label"])}</div>'
        if c.get("items"):
            inner = f'<div class="card {"note2" if good else "note"} {"rot-r" if good else "rot-l"}"><ul>' + "".join(f"<li><span>{rich(i)}</span></li>" for i in c["items"]) + "</ul></div>"
        else:
            inner = f'<div class="bubble {"hand" if c.get("hand") else ""}">{rich(c["text"])}</div>'
        return f'<div class="{"good" if good else "bad"}">{lbl}{inner}</div>'
    return (f'<section class="slide">{chrome(n, total, a, brand, ctx["avatar"])}<div class="body">{title_html(s["title"])}{intro_html(s)}'
            f'<div class="grow"><div class="cols" style="flex:1">{col(s["left"], False)}{col(s["right"], True)}</div>{band_html(s, ctx, True)}</div>{note_html(s, "Rule")}</div></section>')


def s_stats(s, n, total, a, brand, ctx):
    tiles = "".join(f'<div class="tile"><div class="v">{esc(t["value"])}</div><div class="l">{rich(t["label"])}</div></div>' for t in s["tiles"])
    cls = "tiles three" if len(s["tiles"]) in (3, 6) else "tiles"
    if s.get("photo"):
        cls += " withband"
    return (f'<section class="slide">{chrome(n, total, a, brand, ctx["avatar"])}<div class="body">{title_html(s["title"])}{intro_html(s)}'
            f'<div class="{cls}">{tiles}</div>{band_html(s, ctx, True)}{note_html(s, "Why it matters")}</div></section>')


def s_shot(s, n, total, a, brand, ctx):
    img = optimized(s["image"], ctx["img"], 1300)
    bullets = ""
    if s.get("bullets"):
        bullets = '<ul class="pts compact">' + "".join(f'<li><span class="ic check"></span><div>{rich(b)}</div></li>' for b in s["bullets"]) + "</ul>"
    cap = f'<p class="caption">{rich(s["caption"])}</p>' if s.get("caption") else ""
    url = s.get("url", brand)
    if s.get("frame", True):
        fig = (f'<a class="browser grow" href="{attr(href(url))}" style="flex:1 1 auto;min-height:380px"><div class="tape tr pop"></div><div class="bar"><i></i><i></i><i></i><div class="url">{esc(url)}</div></div>'
               f'<img src="{furl(img)}"></a>')
    else:  # the image already has its own device frame (e.g. a phone mockup): plain rounded card
        fig = f'<a class="plain grow" href="{attr(href(url))}" style="flex:1 1 auto;min-height:380px"><img src="{furl(img)}"></a>'
    return (f'<section class="slide">{chrome(n, total, a, brand, ctx["avatar"])}<div class="body">{title_html(s["title"])}{intro_html(s)}'
            f'{fig}{cap}{bullets}{note_html(s, "Try it")}</div></section>')


def s_steps(s, n, total, a, brand, ctx):
    steps = "".join(f'<div class="step"><div class="n">{i+1}</div><div><h4>{rich(st["title"])}</h4><p>{rich(st["desc"])}</p></div></div>'
                    for i, st in enumerate(s["steps"]))
    wb = " withband" if s.get("photo") else ""
    return (f'<section class="slide">{chrome(n, total, a, brand, ctx["avatar"])}<div class="body">{title_html(s["title"])}{intro_html(s)}'
            f'<div class="card grow{wb}" style="flex:1"><div class="tape tr pop"></div><div class="steps">{steps}</div></div>{band_html(s, ctx, True)}{note_html(s, "Rule")}</div></section>')


def s_quote(s, n, total, a, brand, ctx):
    photo = ""
    if s.get("photo"):
        src, _cap, face = photo_spec(s["photo"])
        p = face_crop(src, ctx["img"], 420, 420, face=face)
        photo = f'<img src="{furl(p)}" style="position:absolute;right:64px;bottom:150px;width:420px;height:420px;border-radius:30px;object-fit:cover;border:8px solid #fff;box-shadow:0 18px 44px rgba(0,0,0,.18);z-index:6;transform:rotate(2deg)">'
    return (f'<section class="slide">{chrome(n, total, a, brand, ctx["avatar"])}'
            f'<div class="body"><div class="card note rot-l" style="max-width:660px;margin-top:70px"><div class="tape tl"></div>'
            f'<p class="quote">“{rich(s["text"])}”</p><div class="by">— {rich(s["by"])}</div></div></div>{photo}</section>')


def s_gallery(s, n, total, a, brand, ctx):
    two = len(s["images"]) <= 4
    w, h = (456, 400) if two else (300, 270)
    figs = "".join(f'<figure class="{"rot-l" if i % 2 == 0 else "rot-r"}"><img src="{furl(face_crop(im["src"], ctx["img"], w, h, face=im.get("face")))}"><figcaption>{rich(im.get("caption", ""))}</figcaption></figure>'
                   for i, im in enumerate(s["images"]))
    return (f'<section class="slide">{chrome(n, total, a, brand, ctx["avatar"])}<div class="body">{title_html(s["title"])}{intro_html(s)}'
            f'<div class="gal {"two" if two else ""}">{figs}</div>{note_html(s, "Note")}</div></section>')


def s_cta(s, n, total, a, brand, ctx):
    lines = "".join(f"<li>{rich(l)}</li>" for l in s.get("lines", []))
    soc = "".join(f'<a href="{attr(u)}">{esc(lbl)}</a>' for lbl, u in SOCIALS)
    url = href(s["url"])
    qr = ""
    if s.get("qr", True):
        qp = make_qr(url, ctx["out"] / "qr.png")
        if qp:
            qr = f'<a class="qr" href="{attr(url)}"><img src="{furl(qp)}"><small>scan or tap to open</small></a>'
    portrait = ""
    if s.get("photo"):
        src, _cap, face = photo_spec(s["photo"])
        portrait = f'<img class="portrait" src="{furl(face_crop(src, ctx["img"], 320, 320, face=face))}">'
    return (f'<section class="slide cta">{chrome(n, total, a, brand, ctx["avatar"])}{portrait}'
            f'<div class="body" style="top:200px;gap:28px">{title_html(s["headline"], "h2", "head")}'
            f'<a class="urlpill {"xlong" if len(s["url"]) > 44 else "long" if len(s["url"]) > 27 else ""}" href="{attr(url)}">↗ {esc(s["url"])}</a>'
            f'<ul class="lines">{lines}</ul><div class="soc">{soc}</div></div>{qr}</section>')


def s_photo(s, n, total, a, brand, ctx):
    """Full-bleed photo with the text in the bottom 40%; falls back to a 700px photo panel + text on paper
    whenever the face (plus margin) would reach the text zone or no face is found."""
    src, cap, face = photo_spec(s["photo"])
    span = face_span(src, 1080, 1350, face, 0.27)
    full = span is not None and span[1] <= 0.46 and span[0] >= 0.10
    lines = "".join(f"<li>{rich(l)}</li>" for l in s.get("lines", []))
    cap_html = f'<div class="pcap">{rich(cap)}</div>' if cap else ""
    if full:
        img = face_crop(src, ctx["img"], 1080, 1350, face=face, face_y=0.27)
        return (f'<section class="slide pho full">{chrome(n, total, a, brand, ctx["avatar"])}<img class="bg" src="{furl(img)}"><div class="shade"></div>'
                f'<div class="ptext">{cap_html}{title_html(s["title"])}{intro_html(s)}<ul class="plines">{lines}</ul></div></section>')
    span = face_span(src, 1080, 700, face, 0.45)
    extra = " chip-r" if span is not None and span[0] < 0.19 else ""
    img = face_crop(src, ctx["img"], 1080, 700, face=face, face_y=0.45)
    print(f"  photo slide {n}: panel layout (face span {span and tuple(round(x, 2) for x in span)})")
    return (f'<section class="slide pho panel{extra}">{chrome(n, total, a, brand, ctx["avatar"])}<div class="ppanel"><img src="{furl(img)}"></div>'
            f'<div class="ptext">{cap_html}{title_html(s["title"])}{intro_html(s)}<ul class="plines">{lines}</ul></div></section>')


BUILDERS = {"cover": s_cover, "points": s_points, "compare": s_compare, "stats": s_stats, "shot": s_shot,
            "steps": s_steps, "quote": s_quote, "gallery": s_gallery, "cta": s_cta, "photo": s_photo}


# ----------------------------------------------------------------------------- render
def make_qr(url: str, out: Path) -> Path | None:
    try:
        import segno
        segno.make(url, error="m").save(str(out), scale=8, border=1, dark="#111111", light="#ffffff")
        return out
    except Exception as e:  # noqa: BLE001
        print("  (qr skipped:", str(e)[:60], ")")
        return None


def build_html(deck: dict) -> str:
    theme = THEMES[deck.get("theme", "violet")]
    author = {**AUTHOR, **deck.get("author", {})}
    brand = deck.get("brand", author["site"])
    slides = deck["slides"]
    pool = deck.get("photo_pool") or []
    if deck.get("image_heavy") and pool:
        k = 0
        for s in slides:
            if s.get("photo") is False:
                del s["photo"]
            elif s["type"] in ("points", "steps", "compare", "stats") and not s.get("photo"):
                s["photo"] = pool[k % len(pool)]
                k += 1
    total = len(slides)
    out_dir = DECKS_OUT / deck["slug"]
    ctx = {"out": out_dir, "img": out_dir / "img", "avatar": face_crop(author["avatar"], out_dir / "img", 200, 200)}
    parts = [BUILDERS[s["type"]](s, i, total, author, brand, ctx) for i, s in enumerate(slides, 1)]
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{esc(deck["title"])}</title><style>{css(theme)}</style></head>'
            f'<body class="{deck.get("theme", "violet")}">{"".join(parts)}</body></html>')


def render(deck_path: Path) -> Path:
    deck = json.loads(Path(deck_path).read_text(encoding="utf-8"))
    slug = deck["slug"]
    out_dir = DECKS_OUT / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    PDF_OUT.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{slug}.html"
    html_path.write_text(build_html(deck), encoding="utf-8")
    pdf_path = PDF_OUT / f"{slug}.pdf"
    if not CHROME:
        raise SystemExit("No Chrome/Edge found for PDF rendering")
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--allow-file-access-from-files", "--no-pdf-header-footer",
           "--run-all-compositor-stages-before-draw", "--virtual-time-budget=1200",
           f"--print-to-pdf={pdf_path}", furl(html_path)]
    subprocess.run(cmd, capture_output=True, timeout=300)
    if not pdf_path.exists() or pdf_path.stat().st_size < 10_000:
        raise SystemExit(f"PDF render failed for {slug}")
    try:
        import fitz
        from PIL import Image
        doc = fitz.open(str(pdf_path))
        for f in out_dir.glob("p*.png"):
            f.unlink()
        thumbs = []
        links = 0
        for i, page in enumerate(doc, 1):
            p = out_dir / f"p{i:02d}.png"
            page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5)).save(str(p))
            thumbs.append(Image.open(p))
            links += len(page.get_links())
        cols = 4
        w, h = thumbs[0].size
        rows = (len(thumbs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * w + (cols + 1) * 16, rows * h + (rows + 1) * 16), "#e9e6df")
        for i, t in enumerate(thumbs):
            sheet.paste(t, (16 + (i % cols) * (w + 16), 16 + (i // cols) * (h + 16)))
        sheet.save(out_dir / f"{slug}-sheet.jpg", quality=82)
        print(f"  {len(doc)} pages, {links} links -> {pdf_path.name} ({pdf_path.stat().st_size // 1024} KB); previews in {out_dir}")
    except Exception as e:  # noqa: BLE001
        print("  previews skipped:", str(e)[:80])
    return pdf_path


def main(argv: list[str]) -> None:
    paths = sorted((ROOT / "data" / "carousels").glob("*.json")) if (not argv or argv[0] == "--all") else [Path(p) for p in argv]
    for p in paths:
        print("rendering", p.name)
        render(p)


if __name__ == "__main__":
    main(sys.argv[1:])
