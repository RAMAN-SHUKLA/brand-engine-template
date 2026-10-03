"""LinkedIn carousel (PDF document post) generator.

A deck is a JSON file in data/carousels/<slug>.json describing slides with a small set of typed
components (cover, points, compare, stats, shot, steps, quote, cta). render.py turns it into a
1080x1350 (4:5) multi-page PDF via headless Chrome, plus per-page PNG previews and a contact sheet.

Design system: "notebook deck" -- textured off-white paper with a faint grid, an author chip
(avatar + name + handle) on every slide, a big handwritten slide number, headline set in a heavy
geometric sans with the second line in the deck's accent colour or in a handwritten face, and
sticky-note / tape / browser-frame components for the body. Everything is code, so every deck in
the series looks like one hand made it.
"""
