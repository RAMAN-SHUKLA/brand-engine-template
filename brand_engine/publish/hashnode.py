"""Hashnode publishing via the public GraphQL API (https://gql.hashnode.com).
Token: hashnode.com/settings/developer -> Personal Access Token."""
from __future__ import annotations
import os
import requests
from ..util import slugify

GQL = "https://gql.hashnode.com"


def _call(query: str, variables: dict, token: str) -> dict:
    r = requests.post(GQL, json={"query": query, "variables": variables}, timeout=60,
                      headers={"Authorization": token, "Content-Type": "application/json"})
    if r.status_code >= 300:
        raise RuntimeError(f"Hashnode HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"Hashnode error: {data['errors']}")
    return data["data"]


def get_publication_id(token: str | None = None) -> str:
    token = token or os.environ.get("HASHNODE_TOKEN")
    q = "query { me { publications(first: 5) { edges { node { id url } } } } }"
    edges = _call(q, {}, token)["me"]["publications"]["edges"]
    if not edges:
        raise RuntimeError("No Hashnode publication found for this token. Create a blog on hashnode.com first.")
    return edges[0]["node"]["id"]


def publish(title: str, body_markdown: str, tags: list[str], publication_id: str | None = None,
            as_draft: bool = True, canonical_url: str | None = None, subtitle: str | None = None,
            token: str | None = None) -> dict:
    token = token or os.environ.get("HASHNODE_TOKEN")
    if not token:
        raise RuntimeError("HASHNODE_TOKEN missing in .env")
    publication_id = publication_id or os.environ.get("HASHNODE_PUBLICATION_ID") or get_publication_id(token)
    inp = {"title": title, "contentMarkdown": body_markdown, "publicationId": publication_id,
           "tags": [{"slug": slugify(t), "name": t} for t in tags[:5]]}
    if subtitle:
        inp["subtitle"] = subtitle[:250]
    if canonical_url:
        inp["originalArticleURL"] = canonical_url
    if as_draft:
        q = "mutation CreateDraft($input: CreateDraftInput!) { createDraft(input: $input) { draft { id slug } } }"
        d = _call(q, {"input": inp}, token)["createDraft"]["draft"]
        return {"platform": "hashnode", "id": d["id"], "url": f"https://hashnode.com/draft/{d['id']}",
                "published": False}
    q = "mutation PublishPost($input: PublishPostInput!) { publishPost(input: $input) { post { id url slug } } }"
    p = _call(q, {"input": inp}, token)["publishPost"]["post"]
    return {"platform": "hashnode", "id": p["id"], "url": p["url"], "published": True}
