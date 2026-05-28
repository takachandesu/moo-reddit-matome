"""
メール通知(SMTP)で投稿完了を通知
Gmail を想定(SMTP_HOST のデフォルトが smtp.gmail.com)。
Gmailの場合「アプリパスワード」が必要(2段階認証を有効にした上で発行)。
他プロバイダでも SMTP_HOST / SMTP_PORT を変えれば使える。
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr


def _get_smtp_config():
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")          # 送信元Gmailアドレス
    password = os.environ.get("SMTP_PASSWORD")  # Gmailアプリパスワード
    to_addr = os.environ.get("NOTIFY_EMAIL_TO", user)  # 宛先(未指定なら自分宛て)
    return host, port, user, password, to_addr


def _send_email(subject: str, html_body: str) -> bool:
    host, port, user, password, to_addr = _get_smtp_config()
    if not user or not password:
        print("[notify] SMTP_USER / SMTP_PASSWORD 未設定 (メール通知スキップ)")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("moo-matome-bot", user))
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(user, [to_addr], msg.as_string())
        return True
    except Exception as e:
        print(f"[notify] メール送信エラー: {e}")
        return False


def notify_post(
    post_url: str,
    post_title: str,
    category_label: str,
    subreddit: str,
    reddit_score: int,
    reddit_comments: int,
    reddit_permalink: str,
    status: str = "publish",
) -> bool:
    """
    投稿完了をメールで通知。
    """
    status_label = "新規まとめ投稿" if status == "publish" else "下書き作成"
    status_jp = "公開中" if status == "publish" else "下書き"

    subject = f"[mooまとめ] {status_jp}: {post_title[:50]}"

    html_body = f"""\
<div style="font-family:sans-serif;line-height:1.7;max-width:600px;">
  <h2 style="margin-bottom:4px;">{status_label}</h2>
  <p style="font-size:1.1em;font-weight:bold;margin:8px 0;">{post_title}</p>
  <table style="border-collapse:collapse;width:100%;margin:12px 0;">
    <tr>
      <td style="padding:6px 10px;background:#f4f4f0;width:120px;">カテゴリ</td>
      <td style="padding:6px 10px;">{category_label}</td>
    </tr>
    <tr>
      <td style="padding:6px 10px;background:#f4f4f0;">ソース</td>
      <td style="padding:6px 10px;">r/{subreddit}</td>
    </tr>
    <tr>
      <td style="padding:6px 10px;background:#f4f4f0;">状態</td>
      <td style="padding:6px 10px;">{status_jp}</td>
    </tr>
    <tr>
      <td style="padding:6px 10px;background:#f4f4f0;">Reddit指標</td>
      <td style="padding:6px 10px;">UP {reddit_score:,} / コメント {reddit_comments:,}</td>
    </tr>
  </table>
  <p style="margin:12px 0;">
    <a href="{post_url}" style="display:inline-block;padding:10px 18px;background:#2c5aa0;
       color:#fff;text-decoration:none;border-radius:6px;">投稿を確認する</a>
  </p>
  <p style="margin:8px 0;">
    元スレ: <a href="{reddit_permalink}">{reddit_permalink}</a>
  </p>
  <p style="color:#888;font-size:0.9em;margin-top:16px;">
    確認して問題があれば、WordPress管理画面から即非公開化してください。
  </p>
</div>
"""
    ok = _send_email(subject, html_body)
    if ok:
        print("[notify] メール通知 送信成功")
    return ok


def notify_error(error_message: str) -> bool:
    """
    エラー発生時にメールで通知。
    """
    subject = "[mooまとめ] エラー発生"
    html_body = f"""\
<div style="font-family:sans-serif;line-height:1.6;">
  <h2>moo-matome-bot エラー</h2>
  <pre style="background:#f4f4f0;padding:12px;border-radius:6px;white-space:pre-wrap;">{error_message[:2000]}</pre>
</div>
"""
    return _send_email(subject, html_body)
