"""Parse a resume PDF into text, sections and the hyperlinks embedded in it."""
from __future__ import annotations
import re
from pathlib import Path

SECTION_HEADS = ["Summary", "Technical Skills", "Skills", "Experience", "Projects",
                 "Education", "Achievements", "Certifications", "Awards"]


def extract_links(pdf_path: Path) -> list[str]:
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    links: list[str] = []
    for page in reader.pages:
        for annot in (page.get("/Annots") or []):
            obj = annot.get_object()
            if obj.get("/Subtype") == "/Link" and "/A" in obj and "/URI" in obj["/A"]:
                uri = str(obj["/A"]["/URI"])
                if uri not in links:
                    links.append(uri)
    return links


def extract_text(pdf_path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(pdf_path)).pages)


def split_sections(text: str) -> dict[str, str]:
    lines = [l.rstrip() for l in text.splitlines()]
    sections: dict[str, list[str]] = {"Header": []}
    current = "Header"
    for line in lines:
        stripped = line.strip()
        if stripped in SECTION_HEADS:
            current = stripped
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}


_YEAR_RANGE = re.compile(r"(19|20)\d\d\s*[–-]\s*((19|20)\d\d|Present)", re.I)


def _is_header(s: str) -> bool:
    """Company/role/date lines that separate bullet groups (never bullet continuations)."""
    if _YEAR_RANGE.search(s) or s.isupper():
        return True
    return len(s.split()) <= 4 and not s.endswith((".", ",", ";", ")"))


def bullets(text: str) -> list[str]:
    """Join wrapped bullet lines back into single bullets; stop at header lines."""
    out: list[str] = []
    open_bullet = False
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(("•", "-", "–", "*")) and len(s) > 2:
            out.append(s.lstrip("•-–* ").strip())
            open_bullet = True
        elif _is_header(s):
            open_bullet = False
        elif open_bullet and out:
            out[-1] = out[-1] + " " + s
    return out


def parse_resume(pdf_path: str | Path) -> dict:
    pdf_path = Path(pdf_path)
    text = extract_text(pdf_path)
    links = extract_links(pdf_path)
    sections = split_sections(text)
    email = next((l[7:] for l in links if l.startswith("mailto:")), None)
    if not email:
        m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
        email = m.group(0) if m else None
    pick = lambda needle: next((l for l in links if needle in l.lower()), None)
    return {
        "source_file": str(pdf_path),
        "text": text,
        "sections": sections,
        "bullets_by_section": {k: bullets(v) for k, v in sections.items()},
        "links": links,
        "email": email,
        "linkedin": pick("linkedin.com/in/"),
        "github": pick("github.com/"),
        "instagram_reels": [l for l in links if "instagram.com" in l],
        "github_repos": sorted({l for l in links if re.match(r"https://github\.com/[^/]+/[^/]+", l)}),
        "live_urls": [l for l in links if not any(d in l for d in
                      ("github.com", "linkedin.com", "lnkd.in", "instagram.com", "mailto:"))],
    }
