import json
import os
import sqlite3
import urllib.parse
from datetime import datetime

import feedparser
import yaml

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(ROOT_DIR, "config", "topics.yaml")
DB_PATH = os.path.join(ROOT_DIR, "data", "news.db")
DOCS_JSON_PATH = os.path.join(ROOT_DIR, "docs", "data.json")
DOCS_HTML_PATH = os.path.join(ROOT_DIR, "docs", "index.html")

RSS_TEMPLATE = "https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL UNIQUE,
            source TEXT,
            published TEXT,
            fetched_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def normalize_text(text):
    if text is None:
        return ""
    return text.strip()


def build_rss_url(query):
    encoded = urllib.parse.quote(query, safe="")
    return RSS_TEMPLATE.format(query=encoded)


def parse_entry(entry):
    title = normalize_text(entry.get("title"))
    link = normalize_text(entry.get("link"))
    source = normalize_text(entry.get("source", {}).get("title") if isinstance(entry.get("source"), dict) else entry.get("source"))
    published = normalize_text(entry.get("published"))
    return title, link, source, published


def entry_matches_exclude(title, excludes):
    title_lower = title.lower()
    return any(exclude.lower() in title_lower for exclude in excludes)


def fetch_feed(url):
    feed = feedparser.parse(url)
    if feed.bozo:
        raise RuntimeError(f"RSS parse failed: {feed.bozo_exception}")
    return feed.entries


def save_entry(conn, topic_id, title, link, source, published):
    fetched_at = datetime.utcnow().isoformat() + "Z"
    try:
        conn.execute(
            "INSERT INTO news (topic_id, title, link, source, published, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
            (topic_id, title, link, source, published, fetched_at),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def collect_topic(conn, topic):
    topic_id = topic["id"]
    name = topic.get("name", topic_id)
    excludes = topic.get("exclude_keywords", []) or []
    queries = topic.get("queries", []) or []

    total_fetched = 0
    total_saved = 0

    for query in queries:
        rss_url = build_rss_url(query)
        try:
            entries = fetch_feed(rss_url)
        except Exception as exc:
            print(f"[{name}] RSS 取得エラー: {exc}")
            continue

        for entry in entries:
            title, link, source, published = parse_entry(entry)
            if not title or not link:
                continue
            if entry_matches_exclude(title, excludes):
                continue

            total_fetched += 1
            saved = save_entry(conn, topic_id, title, link, source, published)
            if saved:
                total_saved += 1

    print(f"[{name}] fetched={total_fetched}, saved={total_saved}")
    return topic_id, name


def build_docs(conn, topics):
    cursor = conn.execute(
        "SELECT topic_id, title, link, source, published FROM news ORDER BY published DESC, id DESC"
    )
    rows = cursor.fetchall()
    topic_map = {topic["id"]: topic for topic in topics}
    data = {}

    for topic_id, title, link, source, published in rows:
        topic_name = topic_map.get(topic_id, {}).get("name", topic_id)
        data.setdefault(topic_name, []).append(
            {
                "title": title,
                "link": link,
                "source": source,
                "published": published,
            }
        )

    with open(DOCS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    html = generate_html(data)
    with open(DOCS_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)


def generate_html(data):
    items_html = []
    for topic_name, entries in data.items():
        rows = []
        for item in entries:
            published = item["published"] or ""
            source = item["source"] or ""
            rows.append(
                f"<li><a href=\"{item['link']}\" target=\"_blank\">{item['title']}</a> <small>({source} {published})</small></li>"
            )

        items_html.append(
            f"<section><h2>{topic_name}</h2><ul>{''.join(rows)}</ul></section>"
        )

    return """<!DOCTYPE html>
<html lang=\"ja\">
<head>
  <meta charset=\"UTF-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
  <title>ニュース一覧</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 40px; }
    h1 { margin-bottom: 24px; }
    section { margin-bottom: 32px; }
    li { margin-bottom: 12px; }
    small { color: #555; }
  </style>
</head>
<body>
  <h1>ニュース一覧</h1>
  {content}
</body>
</html>""".replace("{content}", "".join(items_html))


def main():
    config = load_config(CONFIG_PATH)
    topics = [t for t in config.get("topics", []) if t.get("enabled", False)]
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(DOCS_JSON_PATH), exist_ok=True)

    conn = ensure_db(DB_PATH)

    for topic in topics:
        collect_topic(conn, topic)

    build_docs(conn, topics)
    conn.close()

    print(f"docs/index.html と docs/data.json を生成しました。")


if __name__ == "__main__":
    main()
