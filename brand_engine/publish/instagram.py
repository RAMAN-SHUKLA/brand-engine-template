"""Independent Instagram Publisher Module.

Publishes multi-slide carousels directly to Instagram Creator / Business accounts
via the official Meta Instagram Graph API without touching or affecting LinkedIn.

Workflow:
1. Takes rendered high-res 1080x1350 JPEG slides.
2. Uploads them to Cloudinary (free tier) to obtain public HTTPS URLs.
3. Creates individual Instagram media containers for each slide (is_carousel_item=True).
4. Creates the parent CAROUSEL container with the caption.
5. Publishes the carousel live to the Instagram profile.
6. Cleans up temporary cloud images.
"""
from __future__ import annotations
import hashlib
import os
import time
from pathlib import Path
import requests
import pymupdf as fitz
from ..paths import ROOT, load_json, save_json

IG_GRAPH_URL = "https://graph.facebook.com/v21.0"


def export_carousel_slides(pdf_path: Path, output_dir: Path, target_w: int = 1080, target_h: int = 1350) -> list[Path]:
    """Extract each PDF page as a high-definition JPEG at exact 1080x1350 pixels (4:5 ratio)."""
    from PIL import Image
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    slide_paths: list[Path] = []
    for i, page in enumerate(doc, 1):
        rect = page.rect
        scale = float(target_w) / rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        dest = output_dir / f"slide_{i:02d}.jpg"
        pix.save(str(dest))
        
        # Ensure exact 1080x1350 (0.80 aspect ratio) to satisfy Meta Graph API rules
        with Image.open(dest) as img:
            if img.size != (target_w, target_h):
                resized = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                resized.save(dest, "JPEG", quality=95)
        slide_paths.append(dest)
    return slide_paths


def upload_to_cloudinary(image_path: Path, cloud_name: str, api_key: str, api_secret: str) -> dict:
    """Upload an image to Cloudinary and return the public secure HTTPS URL."""
    timestamp = int(time.time())
    to_sign = f"folder=brand_engine_instagram&timestamp={timestamp}{api_secret}"
    signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()
    
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    data = {
        "api_key": api_key,
        "timestamp": timestamp,
        "signature": signature,
        "folder": "brand_engine_instagram",
    }
    with open(image_path, "rb") as f:
        files = {"file": f}
        r = requests.post(url, data=data, files=files, timeout=60)
    res = r.json()
    if r.status_code != 200:
        raise RuntimeError(f"Cloudinary upload failed: {res.get('error', {}).get('message', r.text)}")
    return {"url": res["secure_url"], "public_id": res["public_id"]}


def delete_from_cloudinary(public_id: str, cloud_name: str, api_key: str, api_secret: str) -> None:
    """Purge temporary slide image from Cloudinary."""
    timestamp = int(time.time())
    to_sign = f"public_id={public_id}&timestamp={timestamp}{api_secret}"
    signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/destroy"
    requests.post(url, data={
        "public_id": public_id,
        "api_key": api_key,
        "timestamp": timestamp,
        "signature": signature,
    }, timeout=30)


def publish_carousel(
    slide_image_urls: list[str],
    caption: str,
    ig_account_id: str,
    access_token: str,
) -> dict:
    """Publish a multi-item carousel to Instagram Graph API."""
    if not (2 <= len(slide_image_urls) <= 10):
        raise ValueError(f"Instagram carousels require 2-10 items. Got {len(slide_image_urls)}")

    # 1. Warm up CDN caches so Meta's crawler fetches without cold-cache edge timeout
    for idx, img_url in enumerate(slide_image_urls, 1):
        try:
            requests.get(img_url, timeout=10)
        except Exception:
            pass

    # 2. Create individual item containers
    child_container_ids: list[str] = []
    for idx, img_url in enumerate(slide_image_urls, 1):
        print(f"  creating container for slide {idx}/{len(slide_image_urls)}...")
        res = None
        max_attempts = 8
        for attempt in range(1, max_attempts + 1):
            r = requests.post(
                f"{IG_GRAPH_URL}/{ig_account_id}/media",
                data={
                    "image_url": img_url,
                    "is_carousel_item": "true",
                    "access_token": access_token,
                },
                timeout=45,
            )
            res = r.json()
            if "id" in res:
                break
            err_msg = res.get("error", {}).get("message", res)
            wait_s = min(30, attempt * 5)
            print(f"    retry {attempt}/{max_attempts} for slide {idx} after {wait_s}s delay: {err_msg}")
            time.sleep(wait_s)
        if not res or "id" not in res:
            raise RuntimeError(f"Failed to create carousel item {idx}: {res}")
        child_container_ids.append(res["id"])
        time.sleep(2)  # brief throttle

    # 2. Create the parent CAROUSEL container
    print("  creating parent carousel container...")
    time.sleep(3)
    r = requests.post(
        f"{IG_GRAPH_URL}/{ig_account_id}/media",
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(child_container_ids),
            "caption": caption,
            "access_token": access_token,
        },
        timeout=45,
    )
    res = r.json()
    if "id" not in res:
        raise RuntimeError(f"Failed to create parent carousel container: {res}")
    creation_id = res["id"]

    # Allow container processing
    time.sleep(5)

    # 3. Publish the carousel container
    print("  publishing carousel live to Instagram...")
    r = requests.post(
        f"{IG_GRAPH_URL}/{ig_account_id}/media_publish",
        data={
            "creation_id": creation_id,
            "access_token": access_token,
        },
        timeout=45,
    )
    publish_res = r.json()
    if "id" not in publish_res:
        raise RuntimeError(f"Failed to publish carousel: {publish_res}")

    post_id = publish_res["id"]
    
    # 4. Fetch permalink
    time.sleep(2)
    p_info = requests.get(
        f"{IG_GRAPH_URL}/{post_id}?fields=permalink,shortcode&access_token={access_token}",
        timeout=30,
    ).json()
    permalink = p_info.get("permalink", f"https://www.instagram.com/p/{post_id}/")

    return {
        "status": "success",
        "post_id": post_id,
        "permalink": permalink,
    }
