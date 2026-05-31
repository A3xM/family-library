#!/usr/bin/env python3
"""
Сверка списка летнего чтения с домашней библиотекой в Notion.

БЫСТРЫЙ СТАРТ:
    python check_reading_list.py фото_списка.jpg
    python check_reading_list.py фото.heic --child "Миша" --year 2026

КАК РАБОТАЕТ:
    1. Извлекает список книг из фото через Claude Vision
    2. Загружает библиотеку из Notion (или из кэша library_cache.json)
    3. Сверяет — точное + нечёткое совпадение
    4. Выводит: ✅ есть / ❓ уточнить / ❌ купить
    5. Сохраняет отчёт в файл

НАСТРОЙКА NOTION (одноразово, 30 секунд):
    Чтобы скрипт читал библиотеку напрямую из Notion:
    1. Откройте notion.so → страница «БИБЛИОТЕКА»
    2. Нажмите «···» → Connections → найдите интеграцию «Claude»
    3. Нажмите Connect
    После этого скрипт будет всегда работать с актуальной библиотекой.

    Если не настроено — используется кэш library_cache.json (обновляйте вручную).
"""

import os
import sys
import json
import base64
import argparse
import subprocess
import tempfile
from pathlib import Path
from difflib import SequenceMatcher

import requests
import anthropic

# ── Конфигурация (из env — для Railway/Render; фоллбек на хардкод для локальной разработки)

NOTION_TOKEN  = os.environ.get("NOTION_TOKEN",  "")
NOTION_DB_ID  = os.environ.get("NOTION_DB_ID",  "")
AUTHORS_DB_ID = os.environ.get("AUTHORS_DB_ID", "")
GENRES_DB_ID  = os.environ.get("GENRES_DB_ID",  "")
NOTION_HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type":   "application/json",
}

CACHE_FILE      = Path(__file__).parent / "library_cache.json"
FUZZY_THRESHOLD = 0.72
VISION_MODEL    = "claude-opus-4-5"


def _load_env_key() -> str:
    """Load ANTHROPIC_API_KEY from .env file if not set in environment."""
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


# Ensure API key is available — set even if env var exists but is empty
_api_key = os.environ.get("ANTHROPIC_API_KEY") or _load_env_key()
if _api_key:
    os.environ["ANTHROPIC_API_KEY"] = _api_key


# ── Шаг 0: конвертация HEIC → JPEG ───────────────────────────────────────────

def ensure_jpeg(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() not in (".heic", ".heif"):
        return path
    # sips есть только на macOS
    sips = subprocess.run(["which", "sips"], capture_output=True).returncode == 0
    if not sips:
        return path   # на Linux пропускаем конвертацию, работаем с оригиналом
    out = Path(tempfile.mktemp(suffix=".jpg"))
    r = subprocess.run(
        ["sips", "-s", "format", "jpeg", str(p), "--out", str(out)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return path   # не удалось сконвертировать — вернём оригинал
    print(f"   HEIC → JPEG: {out.name}")
    return str(out)


# ── Шаг 1: OCR фото ──────────────────────────────────────────────────────────

# Путь к скомпилированному бинарнику Vision OCR (macOS, бесплатно)
VISION_OCR_BIN  = Path(__file__).parent / "vision_ocr"
# Исходник Swift — перекомпилируем если бинарник отсутствует
VISION_OCR_SRC  = """
import Vision
import Foundation
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let req = VNRecognizeTextRequest()
req.recognitionLanguages = ["ru-RU", "en-US"]
req.recognitionLevel = .accurate
req.usesLanguageCorrection = true
let h = VNImageRequestHandler(url: url, options: [:])
try? h.perform([req])
(req.results ?? []).forEach { obs in
  if let t = obs.topCandidates(1).first { print(t.string) }
}
"""


def _ensure_vision_ocr_bin() -> bool:
    """Проверяет/компилирует бинарник OCR. Только на macOS."""
    import platform
    if platform.system() != "Darwin":
        return False   # на Linux Vision Framework недоступен
    if VISION_OCR_BIN.exists():
        return True
    swiftc = subprocess.run(["which", "swiftc"], capture_output=True, text=True).stdout.strip()
    if not swiftc:
        return False
    src = Path(tempfile.mktemp(suffix=".swift"))
    src.write_text(VISION_OCR_SRC)
    try:
        r = subprocess.run([swiftc, str(src), "-o", str(VISION_OCR_BIN)],
                           capture_output=True, timeout=120)
        return r.returncode == 0 and VISION_OCR_BIN.exists()
    except Exception:
        return False
    finally:
        src.unlink(missing_ok=True)


def ocr_image_free(image_path: str) -> str:
    """
    Бесплатное OCR через macOS Vision Framework.
    Возвращает сырой текст со страницы или '' если недоступно.
    """
    if not _ensure_vision_ocr_bin():
        return ""
    # Vision принимает любой формат (HEIC, JPG, PNG)
    try:
        r = subprocess.run([str(VISION_OCR_BIN), image_path],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception:
        return ""


PROMPT = """На этом фото — список книг для летнего чтения.

Извлеки все книги. Верни ТОЛЬКО валидный JSON-массив без пояснений:
[
  {"title": "Название книги", "author": "Автор если указан, иначе null"},
  ...
]

Правила:
- Название точно как написано, без номеров пунктов
- Автор: null если не указан
- Не добавляй книги которых нет на фото"""


def extract_books_from_photo(image_path: str) -> list[dict]:
    """
    Извлекает список книг с фото.
    Сначала пробует Claude Vision (если есть API-ключ и баланс),
    при ошибке — бесплатный OCR через macOS Vision + текстовый парсер.
    """
    # ── Попытка 1: Claude Vision API ─────────────────────────────────────────
    if _api_key:
        try:
            client = anthropic.Anthropic(api_key=_api_key)
            ext = Path(image_path).suffix.lower()
            media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".png": "image/png", ".webp": "image/webp"}
            media_type = media.get(ext, "image/jpeg")
            with open(image_path, "rb") as f:
                data = base64.standard_b64encode(f.read()).decode("utf-8")
            resp = client.messages.create(
                model=VISION_MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": PROMPT},
                ]}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return json.loads(raw)
        except Exception as e:
            err = str(e)
            # Недостаточно кредитов или другая API-ошибка → переключаемся на OCR
            print(f"   ⚠️  Claude Vision недоступен ({err[:80]}), использую macOS OCR")

    # ── Попытка 2: macOS Vision OCR + текстовый парсер ───────────────────────
    print("   🔍  OCR через macOS Vision Framework (бесплатно)…")
    raw_text = ocr_image_free(image_path)
    if not raw_text:
        raise RuntimeError("Не удалось распознать текст на фото. "
                           "Проверьте качество изображения.")
    books = extract_books_from_text(raw_text)
    if not books:
        raise RuntimeError("Текст распознан, но книги не найдены. "
                           "Попробуйте вставить список вручную во вкладке «Текстом».")
    return books


# ── Извлечение книг из текста ─────────────────────────────────────────────────

import re as _re

# Паттерны для «кавычек-ёлочек» и "прямых кавычек"
_QUOTED_TITLE = _re.compile(r'[«""]([^»""]+)[»""]')
# Ведущие маркеры: "1.", "1)", "•", "►", "▲", "-", "–"
_BULLET = _re.compile(r'^[\d]+[.)]\s*|^[•►▲▸▶\-–—*]\s*')
# Раздел / заголовок: строка без кавычек длиной < 60 и без явного разделителя
_SECTION_LIKE = _re.compile(r'^[А-ЯЁA-Z][^а-яёa-z«""\-–—]{3,}$')


def _join_wrapped_lines(text: str) -> str:
    """
    Склеивает строки, разбитые OCR при переносе.
    Признак продолжения: незакрытая «» или строка без маркера/автора в начале.
    """
    raw = text.splitlines()
    joined: list[str] = []
    for line in raw:
        stripped = line.strip()
        if not stripped:
            joined.append("")
            continue
        # Строка — продолжение предыдущей, если:
        # 1. Предыдущая строка имеет нечётное число открывающих «» (незакрыта)
        # 2. Текущая строка не начинается с маркера/автора/заглавной буквы раздела
        if joined:
            prev = joined[-1]
            open_q  = prev.count("«") + prev.count("“")
            close_q = prev.count("»") + prev.count("”")
            unclosed = open_q > close_q
            no_marker = not _BULLET.match(stripped) and not stripped[0].isupper()
            if unclosed or (no_marker and prev and not prev.endswith(":")):
                joined[-1] = prev.rstrip() + " " + stripped
                continue
        joined.append(stripped)
    return "\n".join(joined)


def extract_books_from_text(text: str) -> list[dict]:
    """
    Парсит произвольный текстовый список книг без обращения к API.

    Поддерживаемые форматы строк:
      - А.С. Пушкин «Евгений Онегин», «Медный всадник»
      - Н.М. Карамзин «Бедная Лиза»
      - Горе от ума — А.С. Грибоедов
      - 1. Название книги
      - Название книги / Автор
      - Просто название
    """
    text = _join_wrapped_lines(text)
    books: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Убираем маркеры списка
        line = _BULLET.sub("", line).strip()
        if not line or len(line) < 3:
            continue

        # Пропускаем заголовки разделов, служебные и мусорные строки
        lower = line.lower()
        if line.endswith(":") and len(line) < 80 and "«" not in line:
            continue
        if any(kw in lower for kw in ("список книг", "летнее чтение", "класс)", "класс.", " класс",
                                       "портфель", "филолог", "аддисо")):
            if "«" not in line:
                continue
        # Строка без кавычек и без тире — слишком короткая, чтобы быть книгой
        if len(line) < 6 and "«" not in line:
            continue
        # Строка начинается с @ или # — соцсети / watermark
        if line.startswith(("@", "#")):
            continue

        # ── Формат: Автор «Название 1», «Название 2» ──
        quoted = _QUOTED_TITLE.findall(line)
        if quoted:
            # Находим позицию первой открывающей кавычки
            first_q = min(
                (line.index(c) for c in ("«", "“", '"') if c in line),
                default=len(line),
            )
            before = line[:first_q]
            # Убираем пробелы, запятые, точки с запятой и тире в конце
            author = _re.sub(r'[\s,;—–\-]+$', '', before).strip() or None
            for title in quoted:
                t = title.strip()
                if t:
                    books.append({"title": t, "author": author})
            continue

        # ── Формат: «Название» — Автор  (кавычки в начале) ──
        # уже обработан выше через _QUOTED_TITLE

        # ── Формат: Название — Автор  или  Автор — Название ──
        for sep in (" — ", " – ", " - "):
            if sep in line:
                left, right = line.split(sep, 1)
                left, right = left.strip(), right.strip()
                # Угадываем: если правая часть короче и похожа на ФИО → автор справа
                if right and len(right) < len(left):
                    books.append({"title": left, "author": right})
                else:
                    books.append({"title": right or left, "author": left if right else None})
                break
        else:
            # ── Просто строка — принимаем как название ──
            books.append({"title": line, "author": None})

    return [b for b in books if b.get("title")]


# ── Шаг 2: загрузка библиотеки ───────────────────────────────────────────────

def _fetch_all_db_pages(db_id: str) -> list[dict]:
    """Загружает все страницы из базы данных Notion (с пагинацией)."""
    pages, cursor = [], None
    while True:
        payload: dict = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        try:
            r = requests.post(
                f"https://api.notion.com/v1/databases/{db_id}/query",
                headers=NOTION_HEADERS, json=payload, timeout=15,
            )
        except requests.RequestException:
            break
        if r.status_code != 200:
            break
        data = r.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return pages


def build_author_map() -> dict[str, str]:
    """Возвращает {page_id: имя_автора} из базы Авторы."""
    result = {}
    for page in _fetch_all_db_pages(AUTHORS_DB_ID):
        t = page["properties"].get("Name", {}).get("title", [])
        name = t[0]["plain_text"].strip() if t else ""
        if name:
            result[page["id"]] = name
    return result


def build_genre_map() -> dict[str, str]:
    """Возвращает {page_id: жанр} из базы Жанры."""
    result = {}
    for page in _fetch_all_db_pages(GENRES_DB_ID):
        t = page["properties"].get("Name", {}).get("title", [])
        name = t[0]["plain_text"].strip() if t else ""
        if name:
            result[page["id"]] = name
    return result


def find_or_create_author(name: str, author_map: dict[str, str]) -> str | None:
    """Ищет автора по имени в кэше, при отсутствии создаёт новую страницу."""
    name_lower = name.lower().strip()
    for page_id, author_name in author_map.items():
        if author_name.lower() == name_lower:
            return page_id
    # Создаём новую запись в базе Авторы
    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=NOTION_HEADERS,
        json={
            "parent": {"database_id": AUTHORS_DB_ID},
            "properties": {"Name": {"title": [{"text": {"content": name.strip()}}]}},
        },
        timeout=15,
    )
    if r.status_code in (200, 201):
        page_id = r.json()["id"]
        author_map[page_id] = name.strip()   # обновляем кэш
        return page_id
    return None


def fetch_from_notion() -> list[dict] | None:
    """Пробует загрузить через Notion API. Возвращает None если нет доступа."""
    books = []
    cursor = None
    # Карты строим лениво — только после первого успешного ответа Notion.
    # Это позволяет быстро (15 с вместо 45 с) упасть в кэш при недоступности API.
    author_map: dict[str, str] | None = None
    genre_map:  dict[str, str] | None = None

    while True:
        payload: dict = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor

        try:
            r = requests.post(
                f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
                headers=NOTION_HEADERS, json=payload, timeout=15,
            )
        except requests.RequestException as e:
            print(f"   ⚠️  Сеть недоступна: {e}")
            return None

        if r.status_code == 404:
            return None   # интеграция не подключена к БД
        if r.status_code != 200:
            print(f"   ⚠️  Notion API {r.status_code}: {r.text[:120]}")
            return None

        # Загружаем карты один раз — сразу после первого успешного ответа
        if author_map is None:
            author_map = build_author_map()
        if genre_map is None:
            genre_map = build_genre_map()

        data = r.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            t = props.get("Название", {}).get("title", [])
            title = t[0]["plain_text"] if t else ""
            if not title:
                continue
            fmt        = (props.get("Формат", {}).get("select") or {}).get("name", "")
            year       = props.get("Год издания", {}).get("number")
            exl_no     = props.get("EXL No", {}).get("number")
            date_added = (props.get("Дата внесения в реестр", {}).get("date") or {}).get("start", "")
            to_buy     = props.get("Купить", {}).get("checkbox", False)
            section    = (props.get("Раздел", {}).get("select") or {}).get("name", "")
            age        = (props.get("Возраст", {}).get("select") or {}).get("name", "")
            pages      = props.get("Кол-во страниц", {}).get("number")
            language   = (props.get("Язык книги", {}).get("select") or {}).get("name", "")
            types      = [t["name"] for t in (props.get("Тип", {}).get("multi_select") or [])]

            # Резолвим реляционное поле Автор → имена
            author_ids = [rel["id"] for rel in (props.get("Автор", {}).get("relation") or [])]
            author = ", ".join(filter(None, (author_map.get(aid, "") for aid in author_ids)))
            # Fallback: текстовое поле «Имя автора»
            if not author:
                author_rt = props.get("Имя автора", {}).get("rich_text", [])
                author = author_rt[0]["plain_text"].strip() if author_rt else ""

            # Резолвим реляционное поле Жанр → список жанров
            genre_ids = [rel["id"] for rel in (props.get("Жанр", {}).get("relation") or [])]
            genres = [genre_map[gid] for gid in genre_ids if gid in genre_map]

            for_whom = (props.get("Для кого", {}).get("select") or {}).get("name", "")

            books.append({"title": title, "format": fmt, "year": year,
                          "exl_no": exl_no, "date_added": date_added,
                          "to_buy": to_buy, "section": section,
                          "age": age, "pages": pages, "language": language,
                          "types": types, "author": author, "genres": genres,
                          "for_whom": for_whom, "page_id": page["id"]})

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return books


def load_from_cache() -> list[dict]:
    """Загружает из локального кэша library_cache.json."""
    if not CACHE_FILE.exists():
        sys.exit(f"❌ Нет ни доступа к Notion, ни кэша {CACHE_FILE}.\n"
                 "   Подключите интеграцию в Notion или создайте кэш.")
    with open(CACHE_FILE, encoding="utf-8") as f:
        data = json.load(f)
    books = data.get("books", data) if isinstance(data, dict) else data
    return [{
        "title":      b["title"],
        "format":     b.get("format", ""),
        "year":       b.get("year"),
        "exl_no":     b.get("exl_no"),
        "date_added": b.get("date_added", ""),
        "to_buy":     b.get("to_buy", False),
        "section":    b.get("section", ""),
        "age":        b.get("age", ""),
        "pages":      b.get("pages"),
        "language":   b.get("language", ""),
        "types":      b.get("types", []),
        "author":     b.get("author", ""),
        "genres":     b.get("genres", []),
        "for_whom":   b.get("for_whom", ""),
        "page_id":    b.get("page_id", ""),
    } for b in books]


def fetch_library(force_cache: bool = False) -> tuple[list[dict], str]:
    """
    Возвращает (список книг, источник).
    Сначала пробует Notion API, при ошибке — кэш.
    """
    if not force_cache:
        print("   Загружаю из Notion API...")
        books = fetch_from_notion()
        if books is not None:
            print(f"   → {len(books)} книг (Notion API)")
            return books, "Notion API"
        print("   → Notion API недоступен, использую кэш.")
        print("   💡 Для прямого доступа: добавьте интеграцию к базе (см. НАСТРОЙКА NOTION выше)")

    books = load_from_cache()
    print(f"   → {len(books)} книг (кэш {CACHE_FILE.name})")
    return books, f"кэш ({CACHE_FILE.name})"


# ── Поле «Для кого» в базе книг ──────────────────────────────────────────────



def ensure_for_whom_property() -> None:
    """Добавляет поле 'Для кого' в базу книг если его ещё нет."""
    r = requests.patch(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}",
        headers=NOTION_HEADERS,
        json={"properties": {"Для кого": {"select": {"options": [
            {"name": "Альбина", "color": "purple"},
            {"name": "Максим",  "color": "blue"},
            {"name": "Майя",    "color": "pink"},
            {"name": "Миша",    "color": "green"},
        ]}}}},
        timeout=15,
    )
    if r.status_code not in (200, 201):
        print(f"  ⚠️  Не удалось добавить поле 'Для кого': {r.status_code}")


def set_for_whom(page_id: str, name: str) -> None:
    """Устанавливает поле 'Для кого' у книги."""
    r = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=NOTION_HEADERS,
        json={"properties": {"Для кого": {"select": {"name": name}}}},
        timeout=15,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Notion API {r.status_code}: {r.text[:200]}")


# ── Добавление книг в Notion ─────────────────────────────────────────────────

def create_book_in_notion(book: dict) -> dict:
    """Создаёт новую страницу в базе Notion. Возвращает ответ API."""
    props: dict = {
        "Название": {"title": [{"text": {"content": book["title"].strip()}}]},
    }
    if book.get("format"):
        props["Формат"] = {"select": {"name": book["format"]}}
    if book.get("section"):
        props["Раздел"] = {"select": {"name": book["section"]}}
    if book.get("age"):
        props["Возраст"] = {"select": {"name": book["age"]}}
    if book.get("language"):
        props["Язык книги"] = {"select": {"name": book["language"]}}
    if book.get("pages"):
        props["Кол-во страниц"] = {"number": int(book["pages"])}
    if book.get("year"):
        props["Год издания"] = {"number": int(book["year"])}
    if book.get("isbn"):
        props["ISBN"] = {"rich_text": [{"text": {"content": str(book["isbn"])}}]}
    if book.get("author"):
        # Записываем в текстовое поле (всегда) + пробуем relation к базе Авторы
        props["Имя автора"] = {"rich_text": [{"text": {"content": str(book["author"])}}]}
        try:
            author_map = build_author_map()
            author_page_id = find_or_create_author(book["author"], author_map)
            if author_page_id:
                props["Автор"] = {"relation": [{"id": author_page_id}]}
        except Exception as e:
            # Relation не создан, но книга всё равно будет сохранена с текстовым полем автора
            print(f"   ⚠️  Не удалось привязать автора к базе Авторы: {e}")
    if book.get("to_buy"):
        props["Купить"] = {"checkbox": True}
    if book.get("for_whom"):
        props["Для кого"] = {"select": {"name": book["for_whom"]}}
    if book.get("types"):
        props["Тип"] = {"multi_select": [{"name": t} for t in book["types"]]}

    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=NOTION_HEADERS,
        json={"parent": {"database_id": NOTION_DB_ID}, "properties": props},
        timeout=15,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Notion API {r.status_code}: {r.text[:200]}")
    return r.json()


# ── Управление книгами: снять отметку «Купить» ───────────────────────────────

def delete_buy_mark(page_id: str) -> None:
    """Снимает отметку «Купить» у книги в Notion."""
    r = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=NOTION_HEADERS,
        json={"properties": {"Купить": {"checkbox": False}}},
        timeout=15,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Notion API {r.status_code}: {r.text[:200]}")


# ── Спринты летнего чтения ────────────────────────────────────────────────────

SPRINT_DB_FILE    = Path(__file__).parent / ".sprint_db_id"
SPRINT_PARENT_ID  = "98c89665-a5bf-41e0-8020-24f156ed5a29"  # главная страница библиотеки
SPRINT_STATUSES   = ["Беклог", "Прочту в июне", "Прочту в июле", "Прочту в августе",
                     "Читаю сейчас", "Прочитано"]


def get_or_create_sprint_db() -> str:
    """Возвращает ID базы спринтов, создаёт её при отсутствии."""
    # 1. Env var (Railway/production) — приоритет
    env_id = os.environ.get("SPRINT_DB_ID", "").strip()
    if env_id:
        return env_id
    # 2. Локальный файл (разработка)
    if SPRINT_DB_FILE.exists():
        db_id = SPRINT_DB_FILE.read_text().strip()
        if db_id:
            return db_id

    r = requests.post(
        "https://api.notion.com/v1/databases",
        headers=NOTION_HEADERS,
        json={
            "parent": {"type": "page_id", "page_id": SPRINT_PARENT_ID},
            "icon": {"emoji": "📖"},
            "title": [{"type": "text", "text": {"content": "Летнее чтение — Спринты"}}],
            "properties": {
                "Книга":          {"title": {}},
                "Ребёнок":        {"select": {"options": [
                    {"name": "Максим", "color": "blue"},
                    {"name": "Майя",   "color": "pink"},
                    {"name": "Миша",   "color": "green"},
                ]}},
                "Статус":         {"select": {"options": [
                    {"name": "Беклог",           "color": "gray"},
                    {"name": "Прочту в июне",    "color": "blue"},
                    {"name": "Прочту в июле",    "color": "yellow"},
                    {"name": "Прочту в августе", "color": "orange"},
                    {"name": "Читаю сейчас",     "color": "green"},
                    {"name": "Прочитано",        "color": "purple"},
                ]}},
                "Год":            {"number": {}},
                "Автор":          {"rich_text": {}},
                "Заметки":        {"rich_text": {}},
                "Дата прочтения": {"date": {}},
                "Оценка":         {"select": {"options": [
                    {"name": "⭐",     "color": "gray"},
                    {"name": "⭐⭐",   "color": "yellow"},
                    {"name": "⭐⭐⭐", "color": "orange"},
                    {"name": "⭐⭐⭐⭐",  "color": "red"},
                    {"name": "⭐⭐⭐⭐⭐", "color": "purple"},
                ]}},
            },
        },
        timeout=20,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Не удалось создать базу спринтов: {r.status_code}: {r.text[:300]}")
    db_id = r.json()["id"]
    SPRINT_DB_FILE.write_text(db_id)
    return db_id


def ensure_diary_properties() -> None:
    """Добавляет поля читательского дневника в базу спринтов (если их ещё нет)."""
    try:
        db_id = get_or_create_sprint_db()
    except Exception:
        return
    new_props = {
        "Краткое содержание": {"rich_text": {}},
        "Главные герои":      {"rich_text": {}},
        "Главная мысль":      {"rich_text": {}},
        "Любимая цитата":     {"rich_text": {}},
        "Вопросы автору":     {"rich_text": {}},
        "Моё мнение":         {"rich_text": {}},
        "Жанр":               {"rich_text": {}},
    }
    r = requests.patch(
        f"https://api.notion.com/v1/databases/{db_id}",
        headers=NOTION_HEADERS,
        json={"properties": new_props},
        timeout=15,
    )
    if r.status_code not in (200, 201):
        print(f"  ⚠️  Не удалось добавить поля дневника: {r.status_code}")


def _rt(props: dict, key: str) -> str:
    """Читает rich_text поле из props Notion."""
    arr = props.get(key, {}).get("rich_text", [])
    return arr[0]["plain_text"] if arr else ""


def get_sprint_items(child: str = "", year: int = 0) -> list[dict]:
    """Загружает спринт из Notion, фильтруя по ребёнку и году."""
    db_id = get_or_create_sprint_db()

    filters: list[dict] = []
    if child:
        filters.append({"property": "Ребёнок", "select": {"equals": child}})
    if year:
        filters.append({"property": "Год", "number": {"equals": year}})

    pages: list[dict] = []
    cursor = None
    while True:
        payload: dict = {"page_size": 100}
        if filters:
            payload["filter"] = {"and": filters} if len(filters) > 1 else filters[0]
        if cursor:
            payload["start_cursor"] = cursor
        r = requests.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers=NOTION_HEADERS, json=payload, timeout=15,
        )
        if r.status_code != 200:
            break
        data = r.json()
        pages.extend(data["results"])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    items = []
    for page in pages:
        if page.get("archived"):
            continue
        props = page["properties"]
        title_arr = props.get("Книга", {}).get("title", [])
        items.append({
            "id":        page["id"],
            "title":     title_arr[0]["plain_text"] if title_arr else "",
            "author":    _rt(props, "Автор"),
            "notes":     _rt(props, "Заметки"),
            "summary":   _rt(props, "Краткое содержание"),
            "heroes":    _rt(props, "Главные герои"),
            "main_idea": _rt(props, "Главная мысль"),
            "quote":     _rt(props, "Любимая цитата"),
            "questions": _rt(props, "Вопросы автору"),
            "opinion":   _rt(props, "Моё мнение"),
            "genre":     _rt(props, "Жанр"),
            "child":     (props.get("Ребёнок", {}).get("select") or {}).get("name", ""),
            "status":    (props.get("Статус",  {}).get("select") or {}).get("name", "Беклог"),
            "rating":    (props.get("Оценка",  {}).get("select") or {}).get("name", ""),
            "year":       props.get("Год", {}).get("number"),
            "date_read": (props.get("Дата прочтения", {}).get("date") or {}).get("start", ""),
        })
    return items


def bulk_add_sprint(books: list[dict], child: str, year: int,
                    status: str = "Беклог") -> int:
    """
    Создаёт записи спринта.
    По умолчанию все книги попадают в «Беклог»; status можно переопределить.
    Возвращает количество добавленных записей.
    """
    db_id = get_or_create_sprint_db()
    added = 0
    for book in books:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json={
                "parent": {"database_id": db_id},
                "properties": {
                    "Книга":   {"title":     [{"text": {"content": book["title"].strip()}}]},
                    "Ребёнок": {"select":    {"name": child}},
                    "Статус":  {"select":    {"name": status}},
                    "Год":     {"number":    year},
                    "Автор":   {"rich_text": [{"text": {"content": book.get("author") or ""}}]},
                },
            },
            timeout=15,
        )
        if r.status_code in (200, 201):
            added += 1
    return added


def _rt_prop(val: str | None) -> dict:
    return {"rich_text": [{"text": {"content": val}}]} if val is not None else {}


def update_sprint_item(
    item_id:   str,
    status:    str | None = None,
    notes:     str | None = None,
    date_read: str | None = None,
    rating:    str | None = None,
    summary:   str | None = None,
    heroes:    str | None = None,
    main_idea: str | None = None,
    quote:     str | None = None,
    questions: str | None = None,
    opinion:   str | None = None,
    genre:     str | None = None,
) -> None:
    """Обновляет все поля дневника / статус / оценку записи спринта."""
    props: dict = {}
    if status    is not None: props["Статус"]               = {"select": {"name": status}}
    if date_read is not None: props["Дата прочтения"]        = {"date": {"start": date_read} if date_read else None}
    if rating    is not None: props["Оценка"]               = {"select": {"name": rating}}
    for key, val in [("Заметки", notes), ("Краткое содержание", summary),
                     ("Главные герои", heroes), ("Главная мысль", main_idea),
                     ("Любимая цитата", quote), ("Вопросы автору", questions),
                     ("Моё мнение", opinion), ("Жанр", genre)]:
        if val is not None:
            props[key] = {"rich_text": [{"text": {"content": val}}]}
    if not props:
        return
    r = requests.patch(
        f"https://api.notion.com/v1/pages/{item_id}",
        headers=NOTION_HEADERS, json={"properties": props}, timeout=15,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Notion API {r.status_code}: {r.text[:200]}")


def delete_sprint_item(item_id: str) -> None:
    """Архивирует (удаляет) запись спринта."""
    r = requests.patch(
        f"https://api.notion.com/v1/pages/{item_id}",
        headers=NOTION_HEADERS, json={"archived": True}, timeout=15,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Notion API {r.status_code}: {r.text[:200]}")


# ── Распознавание обложки книги ───────────────────────────────────────────────

BOOK_COVER_PROMPT = """На этом фото — обложка книги или несколько книг.

Для каждой видимой книги извлеки данные. Верни ТОЛЬКО валидный JSON-массив без пояснений:
[
  {
    "title": "Точное название с обложки",
    "author": "Имя Фамилия автора или null",
    "year": 2024,
    "language": "русский",
    "types": []
  }
]

Правила:
- Один объект на каждую отдельную книгу видимую на фото
- year: число (год издания) если виден, иначе null
- language: "русский", "английский" или другой язык если понятен из текста на обложке
- types: выбирай из этого списка только то, что точно можно определить по обложке:
  детская, мировая классика, публицистика, русская классика, русская проза, советская, современная проза
- Не придумывай книги, которых нет на фото"""


def extract_book_info_from_photo(image_path: str) -> list[dict]:
    """Извлекает данные книг с фото обложек для добавления в библиотеку."""
    client = anthropic.Anthropic(api_key=_api_key)   # reads ANTHROPIC_API_KEY from env

    ext = Path(image_path).suffix.lower()
    media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".png": "image/png", ".webp": "image/webp"}
    media_type = media.get(ext, "image/jpeg")

    with open(image_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")

    resp = client.messages.create(
        model=VISION_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": [
            {"type": "image",
             "source": {"type": "base64", "media_type": media_type, "data": data}},
            {"type": "text", "text": BOOK_COVER_PROMPT},
        ]}],
    )

    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            result = [result]
        return result
    except json.JSONDecodeError:
        return []


# ── Шаг 3: сверка ────────────────────────────────────────────────────────────

def normalize(s: str) -> str:
    return (s.lower()
             .replace("ё", "е").replace("й", "й")
             .replace("«", "").replace("»", "")
             .replace('"', "").replace("'", "")
             .replace("–", " ").replace("—", " ").replace("-", " ")
             .replace("  ", " ").strip())


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def find_in_library(title: str, library: list[dict]) -> tuple[str, dict | None, float]:
    norm = normalize(title)

    # 1. Точное
    for book in library:
        if normalize(book["title"]) == norm:
            return "found", book, 1.0

    # 2. Префиксное: «Фауст» совпадает с «Фауст (перевод Пастернака)»
    #    Запрос — начало названия в библиотеке (минимум 4 символа, за запросом пробел/скобка)
    if len(norm) >= 4:
        for book in library:
            lib_norm = normalize(book["title"])
            if lib_norm.startswith(norm) and (
                len(lib_norm) == len(norm)
                or lib_norm[len(norm)] in " (.:,"
            ):
                return "found", book, 0.98

    # 3. Нечёткое — полное название
    best, best_book = 0.0, None
    for book in library:
        s = similarity(title, book["title"])
        if s > best:
            best, best_book = s, book

    # 4. Нечёткое — первые слова (для длинных названий с подзаголовками)
    short = title.split(".")[0].split(":")[0].strip()
    if len(short) > 5 and short != title:
        for book in library:
            lib_short = book["title"].split(".")[0].split(":")[0].strip()
            s = similarity(short, lib_short)
            if s > best:
                best, best_book = s, book

    if best >= FUZZY_THRESHOLD:
        return ("found" if best >= 0.96 else "fuzzy"), best_book, best

    return "not_found", None, 0.0


def check_list(reading_list: list[dict], library: list[dict]) -> dict:
    found, fuzzy, not_found = [], [], []
    for item in reading_list:
        title  = item.get("title", "").strip()
        author = item.get("author") or ""
        status, match, score = find_in_library(title, library)
        entry = {"query_title": title, "query_author": author,
                 "status": status, "match": match, "score": round(score, 3)}
        if status == "found":
            found.append(entry)
        elif status == "fuzzy":
            fuzzy.append(entry)
        else:
            not_found.append(entry)
    return {"found": found, "fuzzy": fuzzy, "not_found": not_found}


# ── Шаг 4: отчёт ─────────────────────────────────────────────────────────────

def fmt_date(iso: str) -> str:
    """2024-03-15 → 15.03.2024"""
    if not iso:
        return ""
    try:
        y, m, d = iso[:10].split("-")
        return f"{d}.{m}.{y}"
    except ValueError:
        return iso[:10]


def book_line(book: dict) -> str:
    parts = [book["title"]]
    if book.get("format"):
        parts.append(f"({book['format']})")
    meta = []
    if book.get("exl_no") is not None:
        meta.append(f"EXL №{int(book['exl_no'])}")
    if book.get("date_added"):
        meta.append(f"внесена {fmt_date(book['date_added'])}")
    if meta:
        parts.append(f"[{' · '.join(meta)}]")
    return "  ".join(parts)


def print_report(results: dict, child: str = "", year: str = "",
                 lib_source: str = "") -> str:
    n_f = len(results["found"])
    n_z = len(results["fuzzy"])
    n_n = len(results["not_found"])
    total = n_f + n_z + n_n

    hdr = "📋 СПИСОК ЛЕТНЕГО ЧТЕНИЯ"
    if child: hdr += f" — {child}"
    if year:  hdr += f"  {year}"

    lines = [
        "=" * 62,
        hdr,
        f"Всего: {total}  │  ✅ есть: {n_f}  │  ❓ уточнить: {n_z}  │  ❌ купить: {n_n}",
        f"Источник библиотеки: {lib_source}",
        "=" * 62,
    ]

    if results["found"]:
        lines.append(f"\n✅  УЖЕ ЕСТЬ В БИБЛИОТЕКЕ ({n_f}):")
        for i, e in enumerate(results["found"], 1):
            lines.append(f"  {i:2}. {book_line(e['match'])}")

    if results["fuzzy"]:
        lines.append(f"\n❓  ВОЗМОЖНО ЕСТЬ — уточните ({n_z}):")
        for i, e in enumerate(results["fuzzy"], 1):
            pct = int(e["score"] * 100)
            lines.append(f"  {i:2}. Ищу:    «{e['query_title']}»")
            lines.append(f"      Найдено: «{e['match']['title']}»  ({pct}% совпад.)")

    if results["not_found"]:
        lines.append(f"\n❌  НЕТ В БИБЛИОТЕКЕ — КУПИТЬ ({n_n}):")
        for i, e in enumerate(results["not_found"], 1):
            a = f" — {e['query_author']}" if e["query_author"] else ""
            lines.append(f"  {i:2}. {e['query_title']}{a}")

    lines.append("\n" + "=" * 62)
    report = "\n".join(lines)
    print(report)
    return report


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Сверка списка летнего чтения с библиотекой Notion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image",         help="Фото списка (.jpg / .png / .heic)")
    parser.add_argument("--child",       default="", help="Имя ребёнка")
    parser.add_argument("--year",        default="", help="Год (например 2026)")
    parser.add_argument("--cache",       action="store_true",
                        help="Принудительно использовать кэш (не обращаться к Notion)")
    parser.add_argument("--out",         default="",
                        help="Директория для сохранения результатов (по умолчанию — рядом с фото)")
    args = parser.parse_args()

    if not Path(args.image).exists():
        sys.exit(f"❌ Файл не найден: {args.image}")

    # 0. Конвертация
    print(f"\n📸  Фото: {args.image}")
    img = ensure_jpeg(args.image)

    # 1. Извлечение
    print("🔍  Распознаю список (Claude Vision)...")
    reading_list = extract_books_from_photo(img)
    print(f"   → Распознано: {len(reading_list)} книг")
    for b in reading_list:
        a = f" / {b['author']}" if b.get("author") else ""
        print(f"     • {b['title']}{a}")

    # 2. Библиотека
    print("\n📚  Загружаю библиотеку...")
    library, lib_source = fetch_library(force_cache=args.cache)

    # 3. Сверка
    print("\n⚙️   Сверяю...")
    results = check_list(reading_list, library)

    # 4. Отчёт
    print()
    report = print_report(results, child=args.child, year=args.year,
                          lib_source=lib_source)

    # 5. Сохранение
    out_dir  = Path(args.out) if args.out else Path(args.image).parent
    stem     = Path(args.image).stem
    suffix   = ("_" + args.child if args.child else "") + ("_" + args.year if args.year else "")
    json_path   = out_dir / f"{stem}{suffix}_result.json"
    report_path = out_dir / f"{stem}{suffix}_report.txt"

    output = {
        "meta": {
            "child": args.child, "year": args.year,
            "lib_source": lib_source,
            "total": len(reading_list),
            "found": len(results["found"]),
            "fuzzy": len(results["fuzzy"]),
            "not_found": len(results["not_found"]),
        },
        "reading_list": reading_list,
        "found":     results["found"],
        "fuzzy":     results["fuzzy"],
        "not_found": results["not_found"],
    }
    json_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")

    print(f"\n💾  Сохранено:")
    print(f"   {json_path}")
    print(f"   {report_path}")

    # Итог — купить
    if results["not_found"]:
        print(f"\n🛒  Нужно купить {len(results['not_found'])} кн.:")
        for e in results["not_found"]:
            a = f" — {e['query_author']}" if e.get("query_author") else ""
            print(f"   • {e['query_title']}{a}")


if __name__ == "__main__":
    main()
