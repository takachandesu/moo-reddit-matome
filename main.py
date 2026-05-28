"""
moo-reddit-matome エントリポイント

実行フロー:
1. 投稿済みID読み込み(state/posted_ids.json)
2. 4subreddit から候補を取得 + モメンタムスコアリング
3. 上位候補から1件選び、コメントツリーを取得
4. Claude で 5ch風まとめに変換
5. WordPress REST API で投稿
6. Discord に通知
7. 投稿済みIDを更新して保存
"""
from __future__ import annotations

import os
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from src.reddit_fetch import get_top_candidates, fetch_post_with_comments, SUBREDDIT_CATEGORY
from src.claude_summarize import summarize_to_5ch, render_html
from src.wp_post import post_to_wordpress
from src.notifier import notify_post, notify_error

SUBREDDITS = ["wallstreetbets", "stocks", "CryptoCurrency", "Bitcoin"]
STATE_FILE = Path("state/posted_ids.json")
MAX_STORED_IDS = 1000  # state肥大化防止

# 投稿状態: publish=即公開, draft=下書き
# 環境変数 POST_STATUS で上書き可能(デフォルト publish)
POST_STATUS = os.environ.get("POST_STATUS", "publish")

CATEGORY_LABEL_MAP = {
    "matome-us-stocks": "米国株まとめ",
    "matome-crypto": "暗号資産まとめ",
}


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[state] {STATE_FILE} のパース失敗、空で初期化")
    return {"posted": [], "last_updated": None}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 古いIDが多すぎる場合は新しいものだけ残す
    if len(state["posted"]) > MAX_STORED_IDS:
        state["posted"] = state["posted"][-MAX_STORED_IDS:]
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_once() -> int:
    """1回分の実行。0=成功、1=候補なし、2=エラー"""
    state = load_state()
    posted_ids = set(state.get("posted", []))
    print(f"[main] 投稿済みID数: {len(posted_ids)}")

    print(f"[main] サブレディット {len(SUBREDDITS)} 件から候補取得中...")
    candidates = get_top_candidates(SUBREDDITS, posted_ids, top_n=5)
    if not candidates:
        print("[main] 候補なし(品質フィルタで全部弾かれた可能性)")
        return 1

    print(f"[main] 候補上位:")
    for i, p in enumerate(candidates, 1):
        print(f"  {i}. [{p['_subreddit']}] mom={p['_momentum_score']:.1f} "
              f"up={p.get('score', 0)} c={p.get('num_comments', 0)} - {p['title'][:60]}")

    # 上位から順に処理を試みる(失敗したら次)
    for chosen in candidates:
        print(f"\n[main] 処理対象: {chosen['title'][:80]}")
        post_id = chosen.get("id")
        subreddit = chosen.get("_subreddit", "")

        # コメント取得
        print(f"[main] コメントツリー取得中...")
        full = fetch_post_with_comments(subreddit, post_id, comment_limit=50)
        if not full or not full.get("comments"):
            print(f"[main] コメント取得失敗、次の候補へ")
            continue
        post = full["post"]
        post["_subreddit"] = subreddit
        post["_category_slug"] = chosen["_category_slug"]
        comments = full["comments"]
        print(f"[main] コメント {len(comments)} 件取得")

        # Claude で要約
        print(f"[main] Claudeで5ch風変換中...")
        try:
            summary = summarize_to_5ch(post, comments)
        except Exception as e:
            print(f"[main] 要約エラー: {e}")
            traceback.print_exc()
            continue

        if not summary:
            print(f"[main] 要約失敗、次の候補へ")
            continue

        print(f"[main] タイトル: {summary['title']}")
        print(f"[main] タグ: {summary.get('tags', [])}")

        # HTML生成
        content_html = render_html(summary, post)

        # WordPress投稿
        print(f"[main] WordPress投稿中(status={POST_STATUS})...")
        try:
            wp_result = post_to_wordpress(
                title=summary["title"],
                content_html=content_html,
                category_slug=chosen["_category_slug"],
                tags=summary.get("tags", []),
                status=POST_STATUS,
            )
        except Exception as e:
            print(f"[main] WP投稿エラー: {e}")
            traceback.print_exc()
            continue

        if not wp_result:
            print(f"[main] WP投稿失敗、次の候補へ")
            continue

        print(f"[main] 投稿成功: {wp_result['url']}")

        # 通知
        permalink = f"https://reddit.com{post.get('permalink', '')}"
        category_label = CATEGORY_LABEL_MAP.get(chosen["_category_slug"], "まとめ")
        notify_post(
            post_url=wp_result["url"],
            post_title=wp_result["title"],
            category_label=category_label,
            subreddit=subreddit,
            reddit_score=post.get("score", 0),
            reddit_comments=post.get("num_comments", 0),
            reddit_permalink=permalink,
            status=POST_STATUS,
        )

        # State更新
        state["posted"].append(chosen["name"])
        save_state(state)
        print(f"[main] 完了")
        return 0

    print("[main] 全候補で処理失敗")
    return 2


def main():
    try:
        result = run_once()
        sys.exit(result)
    except Exception as e:
        traceback.print_exc()
        notify_error(f"{type(e).__name__}: {e}")
        sys.exit(3)


if __name__ == "__main__":
    main()
