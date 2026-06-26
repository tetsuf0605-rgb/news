import html
import json
import os
import re
import sqlite3
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import yaml

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(ROOT_DIR, "config", "topics.yaml")
DB_PATH = os.path.join(ROOT_DIR, "data", "news.db")
DOCS_JSON_PATH = os.path.join(ROOT_DIR, "docs", "data.json")
DOCS_HTML_PATH = os.path.join(ROOT_DIR, "docs", "index.html")

RSS_TEMPLATE = "https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
SIMILARITY_THRESHOLD = 0.35


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


def entry_matches_deprioritize(title, keywords):
    title_lower = title.lower()
    return any(keyword.lower() in title_lower for keyword in keywords)


def parse_published_datetime(published):
    if not published:
        return None
    try:
        parsed = parsedate_to_datetime(published)
        if parsed is None:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError, IndexError):
        return None


def format_display_date(published):
    parsed = parse_published_datetime(published)
    if parsed is None:
        return "日付不明"
    return f"{parsed.year}年{parsed.month}月{parsed.day}日"


def tokenize_title(title):
    return [token.lower() for token in re.findall(r"[A-Za-z0-9]+|[一-龠々]+", title) if token]


def title_similarity(left, right):
    tokens_a = set(tokenize_title(left))
    tokens_b = set(tokenize_title(right))
    if not tokens_a or not tokens_b:
        return 0.0
    common = tokens_a & tokens_b
    if len(common) < 2:
        return 0.0
    return len(common) / len(tokens_a | tokens_b)


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
        topic_config = topic_map.get(topic_id, {})
        topic_name = topic_config.get("name", topic_id)
        deprioritize_keywords = topic_config.get("deprioritize_keywords", []) or []
        is_deprioritized = entry_matches_deprioritize(title, deprioritize_keywords)
        published_dt = parse_published_datetime(published)
        data.setdefault(topic_name, []).append(
            {
                "title": title,
                "link": link,
                "source": source,
                "published": published,
                "is_deprioritized": is_deprioritized,
                "published_dt": published_dt.isoformat() if published_dt else None,
                "published_date_key": published_dt.strftime("%Y-%m-%d") if published_dt else None,
                "display_date": format_display_date(published),
            }
        )

    with open(DOCS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    html = generate_html(data)
    with open(DOCS_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)


def render_item(item):
    published = item["published"] or ""
    source = item["source"] or ""
    return f"<li><a href=\"{html.escape(item['link'])}\" target=\"_blank\">{html.escape(item['title'])}</a> <small>({html.escape(source)} {html.escape(published)})</small></li>"


def render_group(group):
    if len(group) == 1:
        return render_item(group[0])

    representative = group[0]
    other_items = "".join(render_item(item) for item in group[1:])
    summary = f"{html.escape(representative['title'])} <small>ほか{len(group) - 1}件</small>"
    return f"<li><details><summary>{summary}</summary><ul>{other_items}</ul></details></li>"


def render_groups(items):
    groups = []
    for item in items:
        matched = False
        for group in groups:
            representative = group[0]
            if title_similarity(representative["title"], item["title"]) >= SIMILARITY_THRESHOLD:
                group.append(item)
                matched = True
                break
        if not matched:
            groups.append([item])
    return "".join(render_group(group) for group in groups)


def generate_html(data):
    items_html = []
    for topic_name, entries in data.items():
        if not entries:
            continue

        sorted_entries = sorted(entries, key=lambda item: (item.get("published_dt") or datetime.min), reverse=True)
        grouped_by_date = {}
        for item in sorted_entries:
            date_key = item.get("published_date_key") or "日付不明"
            grouped_by_date.setdefault(date_key, []).append(item)

        topic_html = [f"<section><h2>{html.escape(topic_name)}</h2>"]
        for date_key in grouped_by_date:
            date_items = grouped_by_date[date_key]
            date_label = date_items[0].get("display_date") or date_key
            normal_items = [item for item in date_items if not item.get("is_deprioritized", False)]
            deprioritized_items = [item for item in date_items if item.get("is_deprioritized", False)]

            topic_html.append(f"<h3>{html.escape(date_label)}</h3>")
            if normal_items:
                topic_html.append("<ul>" + render_groups(normal_items) + "</ul>")
            if deprioritized_items:
                topic_html.append('<p><small>関連性の低い記事</small></p>')
                topic_html.append("<ul>" + render_groups(deprioritized_items) + "</ul>")

        topic_html.append("</section>")
        items_html.append("".join(topic_html))

    return """<!DOCTYPE html>
<html lang=\"ja\">
<head>
  <meta charset=\"UTF-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
  <link rel=\"apple-touch-icon\" href=\"icon.png\">
  <link rel=\"manifest\" href=\"manifest.webmanifest\">
  <meta name=\"apple-mobile-web-app-capable\" content=\"yes\">
  <meta name=\"apple-mobile-web-app-status-bar-style\" content=\"black\">
  <meta name=\"apple-mobile-web-app-title\" content=\"レッズニュース\">
  <meta name=\"theme-color\" content=\"#000000\">
  <title>ニュース一覧</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 40px; }
    h1 { margin-bottom: 24px; }
    section { margin-bottom: 32px; }
    li { margin-bottom: 12px; }
    small { color: #555; }
    details { margin-bottom: 8px; }
    summary { cursor: pointer; }
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
