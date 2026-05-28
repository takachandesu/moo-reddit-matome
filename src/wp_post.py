"""
WordPress REST APIで記事を投稿
"""
from __future__ import annotations

import os
import base64
from typing import Optional

import requests


def _auth_header() -> dict:
    user = os.environ["WP_USERNAME"]
    app_password = os.environ["WP_APP_PASSWORD"]
    token = base64.b64encode(f"{user}:{app_password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _get_category_id_by_slug(site_url: str, slug: str) -> Optional[int]:
    """slug からカテゴリIDを取得。"""
    url = f"{site_url.rstrip('/')}/wp-json/wp/v2/categories"
    resp = requests.get(url, params={"slug": slug}, headers=_auth_header(), timeout=15)
    if resp.status_code != 200:
        print(f"[wp] category lookup failed: {resp.status_code}")
        return None
    data = resp.json()
    if not data:
        return None
    return data[0]["id"]


def _ensure_tag_ids(site_url: str, tag_names: list[str]) -> list[int]:
    """タグ名のリストからIDのリストを取得。存在しなければ作成。"""
    if not tag_names:
        return []
    tag_ids = []
    url = f"{site_url.rstrip('/')}/wp-json/wp/v2/tags"
    headers = _auth_header()
    for name in tag_names:
        # 既存タグ検索
        resp = requests.get(url, params={"search": name}, headers=headers, timeout=15)
        existing = [t for t in resp.json() if t["name"].lower() == name.lower()] if resp.status_code == 200 else []
        if existing:
            tag_ids.append(existing[0]["id"])
            continue
        # 新規作成
        create = requests.post(url, json={"name": name}, headers=headers, timeout=15)
        if create.status_code in (200, 201):
            tag_ids.append(create.json()["id"])
        else:
            print(f"[wp] tag create failed for '{name}': {create.status_code}")
    return tag_ids


def post_to_wordpress(
    title: str,
    content_html: str,
    category_slug: str,
    tags: list[str],
    status: str = "publish",
) -> Optional[dict]:
    """
    WordPress に記事を投稿。
    戻り値: {"id": int, "url": str, "title": str} または None
    """
    site_url = os.environ["WP_SITE_URL"].rstrip("/")
    headers = _auth_header() | {"Content-Type": "application/json"}

    # カテゴリID解決
    category_id = _get_category_id_by_slug(site_url, category_slug)
    if category_id is None:
        print(f"[wp] category not found: {category_slug}, falling back to no category")
        categories = []
    else:
        categories = [category_id]

    # タグID解決(存在しなければ作成)
    tag_ids = _ensure_tag_ids(site_url, tags)

    payload = {
        "title": title,
        "content": content_html,
        "status": status,  # "publish" or "draft"
        "categories": categories,
        "tags": tag_ids,
    }

    url = f"{site_url}/wp-json/wp/v2/posts"
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    if resp.status_code not in (200, 201):
        print(f"[wp] post failed: {resp.status_code}")
        print(f"[wp] response: {resp.text[:500]}")
        return None

    data = resp.json()
    return {
        "id": data["id"],
        "url": data.get("link", f"{site_url}/?p={data['id']}"),
        "title": data["title"]["rendered"],
    }


if __name__ == "__main__":
    print("This module is intended to be imported.")
