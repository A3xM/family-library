#!/usr/bin/env python3
"""
Скачивает ВСЕ книги из Notion и сохраняет в library_cache.json.

ИСПОЛЬЗОВАНИЕ:
    python build_cache.py              # полная выгрузка
    python build_cache.py --dry-run    # только проверить соединение

КОГДА НУЖЕН:
    1. Первый запуск после настройки Notion-интеграции
    2. Библиотека обновилась — надо освежить кэш
    3. Запуск без интернета — скачать заранее

НАСТРОЙКА (если ещё не сделано):
    Notion → «База книг» → ··· → Connections → найдите Claude → Connect
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Конфиг ────────────────────────────────────────────────────────────────────

def _load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

NOTION_TOKEN   = os.environ.get("NOTION_TOKEN", "")
NOTION_DB_ID   = os.environ.get("NOTION_DB_ID",   "9fc436dc-5815-43e9-8f26-1952efc1a48d")
AUTHORS_DB_ID  = os.environ.get("AUTHORS_DB_ID",  "518ea4d211dd4bd1bbd7fd2f0c677df4")
GENRES_DB_ID   = os.environ.get("GENRES_DB_ID",   "ae28060b7a094e6797ff2e0fe42de86e")
NOTION_HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type":   "application/json",
}

CACHE_FILE = Path(__file__).parent / "library_cache.json"


# ── Вспомогательные карты ─────────────────────────────────────────────────────

def _fetch_id_name_map(db_id: str) -> dict[str, str]:
    """Возвращает {page_id: name} для вспомогательной базы (авторы, жанры)."""
    result = {}
    cursor = None
    while True:
        payload: dict = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        r = requests.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers=NOTION_HEADERS, json=payload, timeout=20,
        )
        if r.status_code != 200:
            break
        data = r.json()
        for page in data.get("results", []):
            pid = page["id"]
            t = page.get("properties", {})
            # Ищем первое поле-заголовок (title)
            for prop in t.values():
                if prop.get("type") == "title":
                    parts = prop.get("title", [])
                    name = parts[0]["plain_text"] if parts else ""
                    if name:
                        result[pid] = name
                    break
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return result


# ── Загрузка ──────────────────────────────────────────────────────────────────

def fetch_all_books(verbose: bool = True) -> list[dict]:
    if verbose:
        print("   Загружаю карту авторов...")
    author_map = _fetch_id_name_map(AUTHORS_DB_ID)
    if verbose:
        print(f"   → {len(author_map)} авторов")
        print("   Загружаю карту жанров...")
    genre_map = _fetch_id_name_map(GENRES_DB_ID)
    if verbose:
        print(f"   → {len(genre_map)} жанров")

    books = []
    cursor = None
    page_num = 0

    while True:
        payload: dict = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor

        try:
            r = requests.post(
                f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
                headers=NOTION_HEADERS,
                json=payload,
                timeout=20,
            )
        except requests.RequestException as e:
            sys.exit(f"❌ Сеть недоступна: {e}")

        if r.status_code == 401:
            sys.exit(
                "❌ Notion вернул 401 (Unauthorized).\n"
                "   Проверьте, что токен актуален:\n"
                "   notion.so → Settings → Integrations → Claude"
            )
        if r.status_code == 403:
            sys.exit(
                "❌ Notion вернул 403 (Forbidden).\n"
                "   Интеграция не подключена к базе «База книг».\n"
                "   Откройте базу → ··· → Connections → Connect"
            )
        if r.status_code == 404:
            sys.exit(
                "❌ Notion вернул 404 — база не найдена.\n"
                "   Возможно, интеграция не подключена к «База книг».\n"
                "   Откройте базу → ··· → Connections → Connect"
            )
        if r.status_code != 200:
            sys.exit(f"❌ Notion API {r.status_code}:\n{r.text[:300]}")

        data = r.json()
        page_num += 1
        batch = []

        for page in data.get("results", []):
            props = page.get("properties", {})

            # Название
            t = props.get("Название", {}).get("title", [])
            title = t[0]["plain_text"] if t else ""
            if not title:
                continue

            # page_id
            page_id = page.get("id", "")

            # Формат
            fmt = (props.get("Формат", {}).get("select") or {}).get("name", "")

            # Год издания
            year = props.get("Год издания", {}).get("number")

            # Купить?
            to_buy = props.get("Купить", {}).get("checkbox", False)

            # Раздел (select)
            section = (props.get("Раздел", {}).get("select") or {}).get("name", "")

            # Возраст (select)
            age = (props.get("Возраст", {}).get("select") or {}).get("name", "")

            # Язык книги (select)
            language = (props.get("Язык книги", {}).get("select") or {}).get("name", "")

            # Количество страниц
            pages = props.get("Кол-во страниц", {}).get("number")

            # Экслибрис
            exl_no = props.get("EXL No", {}).get("number")

            # Дата внесения в реестр
            date_added = (props.get("Дата внесения в реестр", {}).get("date") or {}).get("start", "")

            # Автор (relation → author_map)
            author_ids = [r["id"] for r in props.get("Автор", {}).get("relation", [])]
            author = ", ".join(filter(None, (author_map.get(aid, "") for aid in author_ids)))
            if not author:
                # fallback: текстовое поле "Имя автора"
                rt = props.get("Имя автора", {}).get("rich_text", [])
                author = rt[0]["plain_text"] if rt else ""

            # Типы (multi_select)
            types = [o["name"] for o in props.get("Тип", {}).get("multi_select", [])]

            # Жанры (relation → genre_map)
            genre_ids = [r["id"] for r in props.get("Жанр", {}).get("relation", [])]
            genres = [genre_map[gid] for gid in genre_ids if gid in genre_map]

            # Для кого (select)
            for_whom = (props.get("Для кого", {}).get("select") or {}).get("name", "")

            batch.append({
                "title":      title,
                "format":     fmt,
                "year":       year,
                "to_buy":     to_buy,
                "section":    section,
                "age":        age,
                "language":   language,
                "pages":      pages,
                "exl_no":     exl_no,
                "date_added": date_added,
                "author":     author,
                "types":      types,
                "genres":     genres,
                "for_whom":   for_whom,
                "page_id":    page_id,
            })

        books.extend(batch)
        if verbose:
            print(f"   Страница {page_num}: +{len(batch)} книг  (итого: {len(books)})")

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return books


# ── Сохранение ────────────────────────────────────────────────────────────────

def save_cache(books: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "_meta": {
            "source":    "Notion — База книг",
            "db_id":     NOTION_DB_ID,
            "updated_at": now,
            "count":     len(books),
        },
        "books": books,
    }
    CACHE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ Кэш сохранён: {CACHE_FILE}  ({len(books)} книг)")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Выгрузка библиотеки из Notion → library_cache.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Только проверить соединение (не сохранять)"
    )
    args = parser.parse_args()

    print("📚  Подключаюсь к Notion...")

    # Проверочный запрос (1 книга)
    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=NOTION_HEADERS,
            json={"page_size": 1},
            timeout=10,
        )
    except requests.RequestException as e:
        sys.exit(f"❌ Нет сети: {e}")

    if r.status_code == 404:
        print(
            "❌ Notion вернул 404.\n"
            "\n"
            "Интеграция не подключена к базе «База книг».\n"
            "Это решается за 30 секунд:\n"
            "\n"
            "  1. Откройте Notion → «База книг»\n"
            "  2. Нажмите ··· (меню страницы) → Connections\n"
            "  3. Найдите интеграцию «Claude» → нажмите Connect\n"
            "  4. Запустите скрипт снова\n"
        )
        sys.exit(1)

    if r.status_code != 200:
        sys.exit(f"❌ Notion API {r.status_code}: {r.text[:200]}")

    total_hint = r.json().get("results", [])
    print(f"   → Соединение OK")

    if args.dry_run:
        print("✅ --dry-run: соединение работает. Запустите без флага для полной выгрузки.")
        return

    books = fetch_all_books(verbose=True)
    print(f"\n   Итого загружено: {len(books)} книг")
    save_cache(books)


if __name__ == "__main__":
    main()
