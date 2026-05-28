# moo-reddit-matome

Reddit の人気スレを Claude で **ガチ5ch風まとめ**に変換し、moo-stock-blog.com に **1日2回自動投稿**するシステム。

## 構成

- **データソース**: Reddit 公開JSONエンドポイント(認証なし、カルマ問題回避)
- **対象 subreddit**: `r/wallstreetbets`, `r/stocks`, `r/CryptoCurrency`, `r/Bitcoin`
- **要約エンジン**: Claude Sonnet 4.6
- **投稿先**: WordPress REST API
- **通知**: メール (Gmail SMTP)
- **実行**: GitHub Actions (JST 08:00 と 21:00、1日2回)

## セットアップ手順

### 1. GitHubリポジトリ作成

このフォルダの内容を新規リポジトリ `moo-reddit-matome` に push。

```bash
git init
git add .
git commit -m "initial commit"
gh repo create moo-reddit-matome --private --source=. --push
```

### 2. WordPress側の準備

#### カテゴリ作成

WordPress管理画面 → 投稿 → カテゴリで以下を作成:

| 名前 | スラッグ | 親 |
|---|---|---|
| まとめ | `matome` | (なし) |
| 米国株まとめ | `matome-us-stocks` | まとめ |
| 暗号資産まとめ | `matome-crypto` | まとめ |

#### アプリケーションパスワード発行

ユーザー → プロフィール → 一番下の「アプリケーションパスワード」セクション →
名前 `reddit-matome-bot` → 「新規アプリケーションパスワードを追加」

表示される `xxxx xxxx xxxx xxxx xxxx xxxx` を控える(再表示不可)。

### 3. メール通知の準備(Gmailアプリパスワード)

GitHub Actions から Gmail 経由でメールを送るには「アプリパスワード」が必要。

1. Googleアカウントで **2段階認証を有効化**(未設定なら)
   - https://myaccount.google.com/security → 「2段階認証プロセス」をオン
2. **アプリパスワードを発行**
   - https://myaccount.google.com/apppasswords にアクセス
   - アプリ名に `moo-matome-bot` と入力 → 「作成」
   - 表示される **16文字のパスワード**(スペース区切り `xxxx xxxx xxxx xxxx`)を控える
3. このパスワードを後で `SMTP_PASSWORD` に設定する(通常のGmailログインパスワードではない点に注意)

> 他のメールプロバイダを使う場合は `SMTP_HOST` と `SMTP_PORT` を変更すればOK。

### 4. GitHub Secrets を設定

リポジトリ → Settings → Secrets and variables → Actions → New repository secret

| Secret名 | 値 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Console で取得した API キー |
| `WP_SITE_URL` | `https://moo-stock-blog.com` (末尾スラッシュなし) |
| `WP_USERNAME` | WordPressのユーザー名 |
| `WP_APP_PASSWORD` | 上で発行した `xxxx xxxx xxxx xxxx xxxx xxxx` |
| `SMTP_USER` | 送信元Gmailアドレス(例: `you@gmail.com`) |
| `SMTP_PASSWORD` | Gmailアプリパスワード(16文字) |
| `NOTIFY_EMAIL_TO` | 通知の宛先メール(省略可。省略時は `SMTP_USER` 宛て) |
| `SMTP_HOST` | 省略可(デフォルト `smtp.gmail.com`) |
| `SMTP_PORT` | 省略可(デフォルト `587`) |

> Gmailを使うなら必須は `SMTP_USER` と `SMTP_PASSWORD` の2つだけ。
> `NOTIFY_EMAIL_TO` `SMTP_HOST` `SMTP_PORT` は省略してOK。

### 5. (オプション)Variables で投稿状態を制御

下書きで始めたいなら:

リポジトリ → Settings → Secrets and variables → Actions → **Variables** タブ →
New repository variable

| Variable名 | 値 |
|---|---|
| `POST_STATUS` | `draft` (下書き) or `publish` (即公開) |

設定しない場合のデフォルトは `publish`(即公開)。

### 6. 動作確認(手動実行)

リポジトリ → Actions → `post-reddit-matome` → Run workflow

ログを確認。成功すれば WordPress に投稿が作成され、Discord に通知が飛ぶ。

## ローカルでのテスト実行

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY="sk-ant-..."
export WP_SITE_URL="https://moo-stock-blog.com"
export WP_USERNAME="あなたのユーザー名"
export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"
export SMTP_USER="you@gmail.com"
export SMTP_PASSWORD="xxxxxxxxxxxxxxxx"  # Gmailアプリパスワード
export POST_STATUS="draft"  # テスト時は下書きで

python main.py
```

## ファイル構成

```
moo-reddit-matome/
├── .github/workflows/post.yml   # 1日2回のスケジュール実行
├── src/
│   ├── reddit_fetch.py          # Reddit取得 + モメンタムスコア
│   ├── claude_summarize.py      # ガチ5ch風変換
│   ├── wp_post.py               # WordPress投稿
│   └── notifier.py              # メール通知(SMTP)
├── state/posted_ids.json        # 投稿済みID(自動更新)
├── main.py                      # エントリポイント
├── requirements.txt
└── README.md
```

## チューニングポイント

### モメンタムスコア (`src/reddit_fetch.py`)

```python
COMMENT_WEIGHT = 3.0  # コメント数の重み(議論があるスレを優遇)
SCORE_WEIGHT = 1.0    # 投票数の重み
AGE_DECAY_EXPONENT = 1.3  # 経過時間の減衰(大きいほど新しい投稿優先)
```

### 品質フィルタ (`src/reddit_fetch.py`)

```python
MIN_SCORE = 100        # 最低投票数
MIN_COMMENTS = 50      # 最低コメント数(5ch風まとめ用に厳しめ)
MAX_AGE_HOURS = 36     # 最大経過時間
```

### 5ch風プロンプト (`src/claude_summarize.py`)

`SYSTEM_PROMPT` の中の「5ch風語彙」を調整。煽りを強めたい / 抑えたい場合はここを編集。

## 後でカルマが貯まったら(認証ありに切り替え)

現在は認証なしの公開JSONエンドポイントを使っているが、Redditアカウントのカルマが
30〜50 貯まったら認証あり(PRAW)に切り替え可能。コードはほぼそのままで、
`reddit_fetch.py` に PRAW 経由の取得関数を追加するだけ。

その時はメモを書き直す。

## トラブルシューティング

### Reddit から 429 が返る

- 認証なしのレート制限(約10req/分)を超えた可能性。
- `reddit_fetch.py` の `time.sleep(random.uniform(1.5, 2.5))` を長めに調整。

### WordPress投稿が失敗する

- ログに HTTP ステータスとレスポンス本文が出るので確認。
- 401 → 認証情報(`WP_USERNAME` / `WP_APP_PASSWORD`)を確認。
- 403 → アプリケーションパスワードの権限不足。
- カテゴリが見つからない → スラッグの綴りを確認。

### Claude の出力が JSON でない

- `claude_summarize.py` のシステムプロンプトを強化(「JSON のみ」を強調)。
- もしくは Claude のバージョンを上げる。

### 同じ投稿が複数回投稿される

- `state/posted_ids.json` が GitHub にコミットされていない可能性。
- ワークフローの permissions が `contents: write` になっているか確認。
