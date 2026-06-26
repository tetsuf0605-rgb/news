# NEWS GitHub Pages Collector

このプロジェクトは、複数トピックのニュース記事を自動収集し、`docs/` フォルダをローカルで確認できる一覧ページとして出力するためのシステムです。

## 目的

- Python スクリプトで Google ニュース RSS を収集
- `docs/` フォルダに一覧ページを生成
- トピック定義を `config/topics.yaml` で管理し、あとから追加しやすくする

## フォルダ構成

- `.github/workflows/` - 将来の GitHub Actions ワークフロー定義
- `config/` - トピック定義や設定の YAML ファイル
- `src/` - Python の収集スクリプトを置く場所
- `data/` - SQLite データベースなどの収集データを保存する場所
- `docs/` - ローカルで開ける公開用の HTML / JSON を配置する場所

## 依存ライブラリ

- `PyYAML`
- `feedparser`

## ローカル実行手順

1. Python 環境を準備します。
2. 依存ライブラリをインストールします。

```bash
python -m pip install -r requirements.txt
```

3. スクリプトを実行します。

```bash
python src/collect.py
```

4. `docs/index.html` をブラウザで開くと、収集したニュース一覧を確認できます。

## トピックの追加方法

`config/topics.yaml` にトピックを追加します。サンプルは以下の通りです。

```yaml
settings:
  dedupe_days: 30

topics:
  - id: urawa_reds
    name: 浦和レッズ
    enabled: true
    queries:
      - 浦和レッズ
      - 浦和レッズ 移籍
    exclude_keywords: []
```

- `id`: トピックのユニーク ID
- `name`: 表示用のトピック名
- `enabled`: 収集対象に含めるかどうか
- `queries`: Google ニュース RSS 検索クエリのリスト
- `exclude_keywords`: タイトルに含まれると除外するキーワード

## 生成物

- `data/news.db` - 保存済みの記事データ
- `docs/data.json` - トピックごとの記事一覧 JSON
- `docs/index.html` - ブラウザで開ける一覧ページ
