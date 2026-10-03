"""Medium has no working write API any more (integration tokens were discontinued), so this
exports a clean HTML file and tells you the two-minute manual path:

  Option A (best for SEO): Medium -> Stories -> Import a story (https://medium.com/p/import)
           -> paste the Dev.to/Hashnode URL. Medium sets the canonical link to the original.
  Option B: open medium.html in a browser, select all, copy, paste into a new Medium story.
"""
from __future__ import annotations
from pathlib import Path
import markdown
from ..paths import write_text

TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{max-width:720px;margin:40px auto;font:18px/1.6 Georgia,serif;color:#222}}
pre{{background:#f4f4f4;padding:12px;overflow:auto;font-size:14px}} code{{font-family:Menlo,monospace}}
h2,h3{{margin-top:1.6em}}</style></head><body>
<h1>{title}</h1><p><em>{subtitle}</em></p>
{body}
{canonical}
</body></html>"""


def export_html(folder: Path, title: str, subtitle: str, body_markdown: str, canonical_url: str | None) -> dict:
    html_body = markdown.markdown(body_markdown, extensions=["fenced_code", "tables", "sane_lists"])
    canonical = f'<p><small>Originally published at <a href="{canonical_url}">{canonical_url}</a></small></p>' if canonical_url else ""
    out = folder / "medium.html"
    write_text(out, TEMPLATE.format(title=title, subtitle=subtitle or "", body=html_body, canonical=canonical))
    return {"platform": "medium", "id": None, "url": None, "published": False, "file": str(out),
            "next_step": ("Import at https://medium.com/p/import using the canonical URL "
                          f"{canonical_url}" if canonical_url else
                          f"Open {out} in a browser, copy everything, paste into a new Medium story")}
