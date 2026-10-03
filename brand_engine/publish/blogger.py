"""Blogger (Google Blogger API v3) publishing.

Auth is OAuth 2.0 with a long-lived REFRESH token obtained once via `python cli.py blogger-auth`
(a "Desktop app" OAuth client you create in Google Cloud; loopback redirect, no server needed).
Env: BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN. Blog id: config publish.blogger.blog_id.

Blogger has no canonical-URL field, so when the article lives elsewhere first (config publish.primary_platform)
every post opens with an "Originally published at <canonical URL>" line.

Gotcha that kills Blogger automations after a week: if the OAuth app is left in "Testing" publishing
status, Google expires refresh tokens after 7 days (token refresh then fails with invalid_grant). Publish
the app to "In production" -- the "unverified app" warning on the consent screen is expected and harmless
for a personal single-user app. README "Blogger setup" walks through it.

Docs: https://developers.google.com/blogger/docs/3.0/reference/posts/insert
"""
from __future__ import annotations
import http.server
import os
import re
import socket
import threading
import time
import urllib.parse
import webbrowser

import requests

API = "https://www.googleapis.com/blogger/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPE = "https://www.googleapis.com/auth/blogger"

_cache: dict = {}


def _creds() -> tuple[str, str, str]:
    vals = {k: os.environ.get(k) for k in ("BLOGGER_CLIENT_ID", "BLOGGER_CLIENT_SECRET", "BLOGGER_REFRESH_TOKEN")}
    missing = [k for k, v in vals.items() if not v]
    if missing:
        raise RuntimeError(f"{', '.join(missing)} missing in .env (run `python cli.py blogger-auth` once; README 'Blogger setup')")
    return vals["BLOGGER_CLIENT_ID"], vals["BLOGGER_CLIENT_SECRET"], vals["BLOGGER_REFRESH_TOKEN"]


def access_token() -> str:
    """Short-lived access token minted from the long-lived refresh token; cached for its lifetime in-process."""
    if _cache.get("tok") and _cache.get("exp", 0) > time.time() + 60:
        return _cache["tok"]
    cid, sec, rt = _creds()
    r = requests.post(TOKEN_URL, data={"client_id": cid, "client_secret": sec, "refresh_token": rt,
                                       "grant_type": "refresh_token"}, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Blogger token refresh failed {r.status_code}: {r.text[:300]} -- if this says invalid_grant, "
                           "the refresh token was revoked or expired (OAuth app still in 'Testing'? tokens die after 7 days); "
                           "publish the app to production and re-run `python cli.py blogger-auth`")
    d = r.json()
    _cache["tok"] = d["access_token"]
    _cache["exp"] = time.time() + int(d.get("expires_in", 3600))
    return _cache["tok"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"}


def sanitize_labels(tags: list[str], limit: int = 10) -> list[str]:
    """Blogger labels: no commas, keep them short, dedupe case-insensitively."""
    out: list[str] = []
    for t in tags or []:
        t = re.sub(r"[,\s]+", " ", str(t)).strip()[:50]
        if t and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    return out[:limit]


def to_html(body_markdown: str) -> str:
    import markdown
    return markdown.markdown(body_markdown, extensions=["fenced_code", "tables", "sane_lists"])


def blog_info(blog_id: str) -> dict:
    r = requests.get(f"{API}/blogs/{blog_id}", headers=_headers(), timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Blogger blogs.get error {r.status_code}: {r.text[:300]}")
    return r.json()


def publish(title: str, body_markdown: str, tags: list[str], blog_id: str, published: bool = True,
            canonical_url: str | None = None) -> dict:
    html = to_html(body_markdown)
    if canonical_url:
        html = (f'<p><em>Originally published at <a href="{canonical_url}">{canonical_url}</a> '
                f'&mdash; that copy is the canonical version and gets updates first.</em></p>\n' + html)
    payload = {"kind": "blogger#post", "blog": {"id": str(blog_id)}, "title": title, "content": html,
               "labels": sanitize_labels(tags)}
    r = requests.post(f"{API}/blogs/{blog_id}/posts", params={"isDraft": "false" if published else "true"},
                      json=payload, headers=_headers(), timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"Blogger error {r.status_code}: {r.text[:500]}")
    d = r.json()
    return {"platform": "blogger", "id": d.get("id"), "url": d.get("url"), "published": published,
            "dashboard": f"https://www.blogger.com/blog/posts/{blog_id}"}


def auth_flow(client_id: str, client_secret: str, open_browser: bool = True, timeout_s: int = 600) -> dict:
    """One-time desktop OAuth: open the consent page, catch the code on a loopback port, exchange it.
    Returns Google's token JSON, which includes refresh_token (access_type=offline + prompt=consent)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    redirect = f"http://localhost:{port}/"
    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in qs or "error" in qs:
                got.update({k: v[0] for k, v in qs.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>brand-engine: Blogger authorised. You can close this tab.</h2>".encode())

        def log_message(self, *args):  # silence the default request log
            pass

    srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent"})
    print("Sign in with the Google account that owns the blog. If the browser did not open, paste this URL:\n  " + url)
    if open_browser:
        webbrowser.open(url)
    deadline = time.time() + timeout_s
    while time.time() < deadline and "code" not in got and "error" not in got:
        time.sleep(0.5)
    srv.shutdown()
    srv.server_close()
    if "error" in got:
        raise RuntimeError(f"Google returned error: {got['error']}")
    if "code" not in got:
        raise RuntimeError(f"timed out after {timeout_s}s waiting for the browser redirect")
    r = requests.post(TOKEN_URL, data={"code": got["code"], "client_id": client_id, "client_secret": client_secret,
                                       "redirect_uri": redirect, "grant_type": "authorization_code"}, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"code exchange failed {r.status_code}: {r.text[:300]}")
    tok = r.json()
    if "refresh_token" not in tok:
        raise RuntimeError("Google did not return a refresh_token. Revoke the app at myaccount.google.com/permissions "
                           "and run blogger-auth again (prompt=consent must be honoured).")
    return tok
