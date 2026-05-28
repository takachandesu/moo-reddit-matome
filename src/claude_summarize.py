"""
Claude APIで Reddit スレッドをガチ5ch風まとめに変換
"""
from __future__ import annotations

import os
import json
import random
import string
from datetime import datetime, timezone, timedelta
from typing import Optional

from anthropic import Anthropic

JST = timezone(timedelta(hours=9))

# Claude モデル(品質重視ならSonnet、コスト重視ならHaiku)
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """あなたは2ch/5ch風まとめサイトの記事作成者です。
Redditの英語スレッドを、ガチガチの5ch風に翻案・要約する仕事をします。

【絶対ルール】
1. 直訳ではなく、5ch民が書きそうな日本語に「翻案」する
2. 元投稿者(>>1)の主張は原文の論点を保ちつつ、関西弁混じりで威勢よく
3. レスは元コメントの内容ベースだが、5ch特有の煽り・自虐・草・絵文字なしの素のテキストで
4. 著作権配慮:元のコメントを丸ごと翻訳しない、要点だけ拾って5ch化する
5. レス数は合計18〜25個程度
6. 内容は投資・金融寄りなので、投資用語は正確に(EPS、PER、IV、ガンマ、ショートスクイーズ等)

【5ch風語彙(積極的に使う)】
- やめとけwww / やめとけって
- 情強/情弱
- ksk(過疎が来た=書き込み少ない場合に)
- 〜やぞ / 〜やん / 〜やわ(関西弁)
- 草 / 大草原
- これ(賛同を簡潔に表す)
- ワイ(一人称)
- ガチホ / 養分 / イナゴ
- ksonワロタ / オワコン / 終わってる
- ようやっとる / よくやった
- 震え声 / (小声) / (白目)

【フォーマット】
各レスは厳密に以下の形式:
```
N: 名無しさん投資家@米株 :YYYY/MM/DD(曜) HH:MM:SS ID:ランダム7文字
本文(1〜4行)

```
- N = 1から始まる連番
- 名無しさん名は subreddit によって決まる(後述)
- 日時は与えられた基準時刻からランダムに数秒〜数分ずつ進める
- ID は英数字混在の7文字をランダム生成、レスごとに変える(同じ人が複数回書くなら同じID)
- 引用は >>数字 を使う

【出力形式】
以下のJSONを返す(他には何も書かない、コードフェンスも不要):
{
  "title": "5ch風の煽り or キャッチータイトル(40文字以内)",
  "lead": "記事冒頭に置く1〜2文の導入(これは普通の日本語で)",
  "tags": ["銘柄シンボル", ...最大5個],
  "thread_text": "1: 名無しさん〜から始まる5chスレ本文(プレーンテキスト)"
}
"""


def _generate_id() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=7))


def _format_post_for_prompt(post: dict, comments: list[dict]) -> str:
    """投稿+コメントをClaude用のプロンプト文字列に整形。"""
    lines = []
    lines.append("【元投稿】")
    lines.append(f"タイトル: {post.get('title', '')}")
    lines.append(f"投稿者: {post.get('author', 'deleted')}")
    lines.append(f"スコア: {post.get('score', 0)} / コメント数: {post.get('num_comments', 0)}")
    lines.append(f"投稿時刻(UTC): {datetime.fromtimestamp(post.get('created_utc', 0), tz=timezone.utc).isoformat()}")
    selftext = (post.get("selftext") or "").strip()
    if selftext:
        # 長すぎる本文は切り詰め
        if len(selftext) > 1500:
            selftext = selftext[:1500] + "...(省略)"
        lines.append(f"本文:\n{selftext}")
    else:
        lines.append("(リンク投稿または本文なし)")

    lines.append("")
    lines.append(f"【コメント(スコア上位 最大20件)】")
    for i, c in enumerate(comments[:20], 1):
        body = c["body"]
        if len(body) > 400:
            body = body[:400] + "...(略)"
        lines.append(f"--- コメント{i} (score={c['score']}, by {c['author']}) ---")
        lines.append(body)
    return "\n".join(lines)


def summarize_to_5ch(post: dict, comments: list[dict]) -> Optional[dict]:
    """
    Reddit投稿とコメントを 5ch風まとめに変換。
    戻り値: {"title": str, "lead": str, "tags": [str], "thread_text": str} または None
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が未設定")

    client = Anthropic(api_key=api_key)

    subreddit = post.get("_subreddit", "")
    name_tag = "名無しさん投資家@米株" if subreddit in {"wallstreetbets", "stocks"} else "名無しさん投資家@暗号資産"

    # 基準時刻(現在のJST)
    now_jst = datetime.now(JST)
    now_str = now_jst.strftime("%Y/%m/%d(") + "月火水木金土日"[now_jst.weekday()] + ") " + now_jst.strftime("%H:%M:%S")

    user_prompt = f"""以下のRedditスレッドを5ch風にまとめてください。

サブレディット: r/{subreddit}
名無しさん名は「{name_tag}」を使ってください。
基準時刻: {now_str}(各レスの日時はここから前後数分でランダムに散らす)

{_format_post_for_prompt(post, comments)}

【追加指示】
- thread_text は18〜25レス程度
- レス番号 >>1 は元投稿者の主張を関西弁で
- 続くレスはコメントを5ch化(直訳じゃなく雰囲気再現)
- 絵文字や顔文字は使わない(草・wwwはOK)
- 投資のリスクある銘柄なら「やめとけwww」「養分」「ガチホ勢震えとる」など適宜
- 上昇相場なら「ノリ遅れ」「乗るしかないこのビッグウェーブに」など
- tags は記事に登場する銘柄ティッカー(例: TSLA, NVDA, BTC)を最大5個

JSON のみ出力してください。"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    # レスポンスからテキスト抽出
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    # コードフェンスがあれば除去
    text = text.strip()
    if text.startswith("```"):
        # ```json ... ``` の場合
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[summarize] JSON parse error: {e}")
        print(f"[summarize] raw text:\n{text[:500]}")
        return None

    # 必須キー確認
    required = {"title", "lead", "tags", "thread_text"}
    if not required.issubset(result.keys()):
        print(f"[summarize] missing keys: {required - set(result.keys())}")
        return None

    return result


def render_html(summary: dict, post: dict) -> str:
    """
    5chスレ風まとめHTMLを生成。WordPress投稿用。
    """
    permalink = f"https://reddit.com{post.get('permalink', '')}"
    subreddit = post.get("_subreddit", "")
    score = post.get("score", 0)
    num_comments = post.get("num_comments", 0)

    html = []
    html.append(f"<p>{summary['lead']}</p>")
    html.append("<hr>")
    html.append("<p><strong>元スレ情報</strong></p>")
    html.append("<ul>")
    html.append(f"<li>サブレディット: <a href='https://reddit.com/r/{subreddit}' target='_blank' rel='nofollow noopener'>r/{subreddit}</a></li>")
    html.append(f"<li>元スレ: <a href='{permalink}' target='_blank' rel='nofollow noopener'>{post.get('title', '')}</a></li>")
    html.append(f"<li>スコア: {score:,} / コメント数: {num_comments:,}</li>")
    html.append("</ul>")
    html.append("<hr>")
    html.append("<p><strong>スレッド</strong></p>")

    # スレ本文を <pre> でモノスペース表示
    thread_text = summary["thread_text"]
    # HTMLエスケープ
    thread_text = thread_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html.append(
        f'<pre style="background:#f4f4f0;padding:1em;border-radius:6px;'
        f'font-family:\'Hiragino Kaku Gothic ProN\',\'Yu Gothic\',monospace;'
        f'white-space:pre-wrap;word-wrap:break-word;line-height:1.7;font-size:0.95em;">'
        f'{thread_text}</pre>'
    )

    html.append("<hr>")
    html.append("<p><small>※本記事はRedditの公開スレッドをもとに、AIで5ch風にまとめたものです。"
                "投資判断は自己責任でお願いします。元スレへのリンクは上記をご参照ください。</small></p>")

    return "\n".join(html)


if __name__ == "__main__":
    # 動作確認(stub)
    print("This module is intended to be imported, not run directly.")
