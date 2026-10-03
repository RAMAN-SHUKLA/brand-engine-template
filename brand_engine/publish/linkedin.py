"""LinkedIn member posts via the Posts API (https://learn.microsoft.com/linkedin/marketing/community-management/shares/posts-api).

Setup (one time, ~15 min, done by you in the browser):
  1. https://www.linkedin.com/developers/apps -> Create app (needs a LinkedIn Page to attach to; create a
     free Company Page on LinkedIn if you don't have one).
  2. Products tab -> request "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect".
  3. Auth tab -> OAuth 2.0 tools -> create a token with scopes: openid profile w_member_social
  4. Paste the token into .env as LINKEDIN_ACCESS_TOKEN (valid ~60 days; regenerate when it expires).

LinkedIn has no "draft" concept through the API, so this module only runs with --live --confirm.
"""
from __future__ import annotations
import os
import re
import requests

API = "https://api.linkedin.com"
# "little text" reserved characters that must be backslash-escaped in `commentary`.
# '#' is left alone so hashtags stay clickable.
_RESERVED = r"\|{}@[]()<>*_~"


def escape_little_text(text: str) -> str:
    return re.sub(r"([%s])" % re.escape(_RESERVED), r"\\\1", text)


def get_person_urn(token: str) -> str:
    explicit = os.environ.get("LINKEDIN_PERSON_URN")
    if explicit:
        return explicit if explicit.startswith("urn:li:") else f"urn:li:person:{explicit}"
    r = requests.get(f"{API}/v2/userinfo", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"LinkedIn userinfo {r.status_code}: {r.text[:300]} "
                           "(token needs scopes: openid profile w_member_social)")
    return f"urn:li:person:{r.json()['sub']}"


def upload_image(path: str, author: str, token: str, api_version: str) -> str:
    """Images API: initializeUpload -> PUT bytes -> urn:li:image:... usable as post media."""
    import mimetypes
    import time
    headers = {"Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0",
               "LinkedIn-Version": api_version, "Content-Type": "application/json"}
    r = requests.post(f"{API}/rest/images?action=initializeUpload", timeout=60, headers=headers,
                      json={"initializeUploadRequest": {"owner": author}})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn image initializeUpload failed {r.status_code}: {r.text[:300]}")
    v = r.json()["value"]
    upload_url, image_urn = v["uploadUrl"], v["image"]
    with open(path, "rb") as f:
        data = f.read()
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    r2 = requests.put(upload_url, data=data, timeout=120,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": ctype})
    if r2.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn image upload failed {r2.status_code}: {r2.text[:300]}")
    # Processing is asynchronous. Wait until LinkedIn reports the image AVAILABLE before attaching it,
    # otherwise the post can be created with the media silently dropped.
    from urllib.parse import quote
    for _ in range(20):
        time.sleep(2)
        try:
            s = requests.get(f"{API}/rest/images/{quote(image_urn, safe='')}", headers=headers, timeout=30)
        except requests.RequestException:
            continue  # transient; keep waiting
        if s.status_code in (401, 403, 404):
            print(f"  LinkedIn image status not readable ({s.status_code}); continuing after a fixed wait")
            time.sleep(4)
            break
        status = s.json().get("status") if s.status_code == 200 else None
        if status == "AVAILABLE":
            break
        if status == "PROCESSING_FAILED":
            raise RuntimeError("LinkedIn image processing failed")
    return image_urn


def upload_document(path: str, author: str, token: str, api_version: str) -> str:
    """Documents API: initializeUpload -> PUT the PDF -> poll until AVAILABLE -> urn:li:document:...
    A document post renders as a swipeable carousel in the feed (LinkedIn's native 'carousel' for
    members is exactly this: a PDF document post). Limits: PDF/PPT/DOC, <=100 MB, <=300 pages."""
    import mimetypes
    import time
    from urllib.parse import quote
    headers = {"Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0",
               "LinkedIn-Version": api_version, "Content-Type": "application/json"}
    r = requests.post(f"{API}/rest/documents?action=initializeUpload", timeout=60, headers=headers,
                      json={"initializeUploadRequest": {"owner": author}})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn document initializeUpload failed {r.status_code}: {r.text[:300]}")
    v = r.json()["value"]
    upload_url, doc_urn = v["uploadUrl"], v["document"]
    with open(path, "rb") as f:
        data = f.read()
    ctype = mimetypes.guess_type(path)[0] or "application/pdf"
    r2 = requests.put(upload_url, data=data, timeout=300,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": ctype})
    if r2.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn document upload failed {r2.status_code}: {r2.text[:300]}")
    for _ in range(30):  # PDFs take longer than images to process; wait until AVAILABLE
        time.sleep(3)
        try:
            s = requests.get(f"{API}/rest/documents/{quote(doc_urn, safe='')}", headers=headers, timeout=30)
        except requests.RequestException:
            continue
        if s.status_code in (401, 403, 404):
            print(f"  LinkedIn document status not readable ({s.status_code}); continuing after a fixed wait")
            time.sleep(8)
            break
        status = s.json().get("status") if s.status_code == 200 else None
        if status == "AVAILABLE":
            break
        if status == "PROCESSING_FAILED":
            raise RuntimeError("LinkedIn document processing failed")
    return doc_urn


def publish_post(commentary: str, article_url: str | None = None, article_title: str | None = None,
                 article_description: str | None = None, api_version: str = "202508",
                 token: str | None = None, image_path: str | None = None, image_alt: str | None = None,
                 document_path: str | None = None, document_title: str | None = None) -> dict:
    token = token or os.environ.get("LINKEDIN_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("LINKEDIN_ACCESS_TOKEN missing in .env")
    if len(commentary) > 3000:
        raise RuntimeError("LinkedIn commentary exceeds 3000 characters")
    author = get_person_urn(token)
    # Hard guarantee: this module only ever posts as the member (personal profile), never as a Page.
    if not author.startswith("urn:li:person:"):
        raise RuntimeError(f"Refusing to post: author {author} is not a personal profile")
    body = {
        "author": author,
        "commentary": escape_little_text(commentary),
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    # A post carries ONE of: a document (PDF carousel), an uploaded image, or an article card.
    if document_path:
        doc_urn = upload_document(document_path, author, token, api_version)
        body["content"] = {"media": {"id": doc_urn, "title": (document_title or os.path.basename(document_path))[:400]}}
    elif image_path:
        image_urn = upload_image(image_path, author, token, api_version)
        body["content"] = {"media": {"id": image_urn, "altText": (image_alt or "")[:4086]}}
    elif article_url:
        body["content"] = {"article": {"source": article_url,
                                       "title": (article_title or article_url)[:400],
                                       "description": (article_description or "")[:4086]}}
    def _send(version: str):
        return requests.post(f"{API}/rest/posts", json=body, timeout=60, headers={
            "Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": version, "Content-Type": "application/json"})

    r = _send(api_version)
    if r.status_code == 426:  # version retired (LinkedIn keeps ~12 months active). Walk back from this month.
        import datetime as _dt
        today = _dt.date.today()
        for back in range(0, 13):
            y, m = today.year, today.month - back
            while m <= 0:
                y, m = y - 1, m + 12
            v = f"{y}{m:02d}"
            if v == api_version:
                continue
            r = _send(v)
            if r.status_code != 426:
                print(f"  LinkedIn-Version {api_version} is retired; {v} worked. Update publish.linkedin.api_version in config.yaml.")
                break
    if r.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn post failed {r.status_code}: {r.text[:500]}")
    urn = r.headers.get("x-restli-id") or r.headers.get("X-RestLi-Id")
    return {"platform": "linkedin", "id": urn, "url": f"https://www.linkedin.com/feed/update/{urn}/",
            "published": True}
