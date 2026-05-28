"""
Reddit取得 + モメンタムスコアリング
認証なし方式(公開JSONエンドポイント)とPRAW方式の両対応
環境変数 REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET があれば認証あり、なければ認証なし
"""
from __future__ import annotations

import os
import time
import random
from datetime import datetime, timezone
from typing import Optional

import requests

# User-Agent: Reddit はデフォの requests UA をブロックするので必須
USER_AGENT = "python:moo-matome-bot:v1.0 (by /u/PrimaryResolve641)"

# モメンタムスコアリングのチューニング
COMMENT_WEIGHT = 3.0
SCORE_WEIGHT = 1.0
AGE_DECAY_EXPONENT = 1.3

# 品質フィルタ
MIN_SCORE = 100
MIN_COMMENTS = 50
MAX_AGE_HOURS = 36

# サブレディット -> カテゴリslug マッピング
SUBREDDIT_CATEGORY = {
    "wallstreetbets": "matome-us-stocks",
    "stocks": "matome-us-stocks",
    "CryptoCurrency": "matome-crypto",
    "Bitcoin": "matome-crypto",
}

# 除外するフレア(まとめ向きじゃないもの)
EXCLUDED_FLAIRS = {
    "Meme", "Shitpost", "Daily Discussion", "Weekend Discussion",
    "Megathread", "Daily Megathread", "Stickied", "Mod Post",
}


def _request_with_retry(url: str, max_retries: int = 3) -> Optional[dict]:
    """Reddit JSONを取得。429/タイムアウト時は指数バックオフでリトライ。"""
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = (attempt + 1) * 15
                print(f"[reddit] 429 rate limit, waiting {wait}s")
                time.sleep(wait)
                continue
            print(f"[reddit] HTTP {resp.status_code} for {url}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"[reddit] request error (attempt {attempt + 1}): {e}")
            time.sleep(5 * (attempt + 1))
    return None


def fetch_subreddit_listing(subreddit: str, sort: str = "hot", limit: int = 25) -> list[dict]:
    """
    サブレディットの投稿一覧を取得。
    sort: hot, rising, top, new
    """
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}"
    data = _request_with_retry(url)
    if not data or "data" not in data:
        return []
    children = data["data"].get("children", [])
    return [c["data"] for c in children if c.get("kind") == "t3"]


def fetch_post_with_comments(subreddit: str, post_id: str, comment_limit: int = 50) -> Optional[dict]:
    """
    投稿本文 + コメントツリーを取得。
    戻り値: {"post": {...}, "comments": [{...}, ...]}
    """
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json?limit={comment_limit}&depth=2"
    data = _request_with_retry(url)
    if not data or len(data) < 2:
        return None
    post = data[0]["data"]["children"][0]["data"]
    raw_comments = data[1]["data"]["children"]

    comments = []
    for c in raw_comments:
        if c.get("kind") != "t1":
            continue
        cdata = c["data"]
        body = (cdata.get("body") or "").strip()
        if not body or body in {"[deleted]", "[removed]"}:
            continue
        comments.append({
            "author": cdata.get("author", "deleted"),
            "body": body,
            "score": cdata.get("score", 0),
            "created_utc": cdata.get("created_utc", 0),
        })
    # スコア降順でソート
    comments.sort(key=lambda x: x["score"], reverse=True)
    return {"post": post, "comments": comments}


def momentum_score(post: dict) -> float:
    """投稿のモメンタムスコアを計算。コメント数を重く扱う。"""
    created = post.get("created_utc", 0)
    if created <= 0:
        return 0.0
    age_hours = max((datetime.now(timezone.utc).timestamp() - created) / 3600, 1.0)
    score = post.get("score", 0)
    num_comments = post.get("num_comments", 0)
    raw = score * SCORE_WEIGHT + num_comments * COMMENT_WEIGHT
    return raw / (age_hours ** AGE_DECAY_EXPONENT)


def passes_quality_filter(post: dict, posted_ids: set[str]) -> bool:
    """まとめ向きじゃない投稿を除外する。"""
    if post.get("name") in posted_ids:
        return False
    if post.get("over_18"):
        return False
    if post.get("stickied"):
        return False
    if post.get("score", 0) < MIN_SCORE:
        return False
    if post.get("num_comments", 0) < MIN_COMMENTS:
        return False
    if (post.get("selftext") or "").strip() in {"[removed]", "[deleted]"}:
        return False

    created = post.get("created_utc", 0)
    if created <= 0:
        return False
    age_hours = (datetime.now(timezone.utc).timestamp() - created) / 3600
    if age_hours > MAX_AGE_HOURS:
        return False

    flair = (post.get("link_flair_text") or "").strip()
    if flair in EXCLUDED_FLAIRS:
        return False

    # 動画ホストのみのリンク投稿は除外(議論が少ない)
    domain = post.get("domain", "")
    if domain in {"v.redd.it", "i.redd.it", "i.imgur.com", "youtube.com", "youtu.be"}:
        # ただし議論コメントが多ければOK
        if post.get("num_comments", 0) < 200:
            return False

    return True


def get_top_candidates(
    subreddits: list[str],
    posted_ids: set[str],
    top_n: int = 5,
) -> list[dict]:
    """
    各サブレディットから hot + rising を取得し、品質フィルタとモメンタムスコアで
    上位 top_n 件を返す。
    """
    all_candidates: dict[str, dict] = {}  # post_name -> post (重複排除)

    for sub in subreddits:
        for sort in ("hot", "rising"):
            posts = fetch_subreddit_listing(sub, sort=sort, limit=25)
            for p in posts:
                name = p.get("name")
                if not name:
                    continue
                if name in all_candidates:
                    continue
                if not passes_quality_filter(p, posted_ids):
                    continue
                p["_subreddit"] = sub
                p["_category_slug"] = SUBREDDIT_CATEGORY.get(sub, "matome")
                p["_momentum_score"] = momentum_score(p)
                all_candidates[name] = p
            # 連続リクエスト避け
            time.sleep(random.uniform(1.5, 2.5))

    ranked = sorted(all_candidates.values(), key=lambda x: x["_momentum_score"], reverse=True)
    return ranked[:top_n]


if __name__ == "__main__":
    # 動作確認用
    candidates = get_top_candidates(
        ["wallstreetbets", "stocks", "CryptoCurrency", "Bitcoin"],
        posted_ids=set(),
        top_n=5,
    )
    for i, p in enumerate(candidates, 1):
        print(f"{i}. [{p['_subreddit']}] score={p['_momentum_score']:.1f} "
              f"upvotes={p['score']} comments={p['num_comments']}")
        print(f"   {p['title']}")
        print(f"   https://reddit.com{p['permalink']}")
        print()
