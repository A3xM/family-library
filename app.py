#!/usr/bin/env python3
"""
Семейная библиотека — веб-приложение
Запуск: python3 app.py
Браузер: http://localhost:8000
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

# ── Импорт логики из check_reading_list.py ────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from check_reading_list import (
    fetch_library, check_list, extract_books_from_photo,
    normalize, ensure_jpeg,
    extract_book_info_from_photo, create_book_in_notion,
    extract_books_from_text,
    delete_buy_mark,
    get_sprint_items, bulk_add_sprint, update_sprint_item, delete_sprint_item,
    get_or_create_sprint_db,
    ensure_for_whom_property, set_for_whom,
    ensure_diary_properties,
)

# ── Библиотека в памяти ───────────────────────────────────────────────────────
_library: List[dict] = []
_lib_source: str = ""


def _load_library(force: bool = False) -> None:
    global _library, _lib_source
    if not _library or force:
        try:
            lib, src = fetch_library(force_cache=False)
            # Если авторов пришло мало (карта не достроилась при загрузке),
            # пробуем кэш — он актуальнее старого пустого ответа
            authors_pct = sum(1 for b in lib if b.get("author")) / max(len(lib), 1)
            if authors_pct < 0.3 and len(lib) > 100:
                print(f"  ⚠️  Авторов мало ({int(authors_pct*100)}%) — пробую кэш")
                try:
                    lib_c, src_c = fetch_library(force_cache=True)
                    auth_c = sum(1 for b in lib_c if b.get("author")) / max(len(lib_c), 1)
                    if auth_c > authors_pct:
                        lib, src = lib_c, src_c + " (авторы)"
                except Exception:
                    pass
            _library, _lib_source = lib, src
        except Exception as e:
            print(f"  ⚠️  Notion недоступен: {e}")
            try:
                lib, src = fetch_library(force_cache=True)
                _library, _lib_source = lib, src
            except Exception as e2:
                print(f"  ❌ Кэш тоже недоступен: {e2}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n📚  Загружаю библиотеку...")
    _load_library()
    print(f"   → {len(_library)} книг ({_lib_source})\n")
    try:
        ensure_for_whom_property()
        ensure_diary_properties()   # поля читательского дневника в базе спринтов
    except Exception:
        pass
    yield


# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="Семейная библиотека", lifespan=lifespan)


# ── API ───────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def api_stats():
    to_buy   = [b for b in _library if b.get("to_buy")]
    with_exl = [b for b in _library if b.get("exl_no") is not None]
    latest   = sorted(
        [b for b in _library if b.get("date_added")],
        key=lambda x: x.get("date_added", ""),
        reverse=True,
    )[:6]
    return {
        "total":    len(_library),
        "to_buy":   len(to_buy),
        "with_exl": len(with_exl),
        "source":   _lib_source,
        "latest":   latest,
    }


@app.get("/api/books")
def api_books(
    q: str       = "",
    section: str = "",
    age: str     = "",
    genre: str   = "",
    sort: str    = "exl",   # exl | date | title | author
    page: int    = 1,
    per_page: int = 48,
):
    results = list(_library)

    if q:
        qn = normalize(q)
        q_is_num = q.strip().lstrip("0").isdigit()
        results = [b for b in results
                   if qn in normalize(b["title"])
                   or qn in normalize(b.get("author", ""))
                   or (q_is_num and b.get("exl_no") == int(q.strip()))]
    if section:
        results = [b for b in results if b.get("section") == section]
    if age:
        results = [b for b in results if b.get("age") == age]
    if genre:
        results = [b for b in results if genre in b.get("genres", [])]

    if sort == "exl":
        results.sort(key=lambda x: (x.get("exl_no") is None, x.get("exl_no") or 0))
    elif sort == "date":
        results.sort(key=lambda x: x.get("date_added") or "", reverse=True)
    elif sort == "title":
        results.sort(key=lambda x: normalize(x["title"]))
    elif sort == "author":
        results.sort(key=lambda x: (not x.get("author"), normalize(x.get("author", ""))))

    total = len(results)
    start = (page - 1) * per_page
    return {
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
        "page":  page,
        "books": results[start: start + per_page],
    }


@app.get("/api/genres")
def api_genres():
    """Возвращает все жанры из загруженной библиотеки, отсортированные по частоте."""
    counts: dict[str, int] = {}
    for b in _library:
        for g in b.get("genres", []):
            if g:
                counts[g] = counts.get(g, 0) + 1
    return sorted(
        [{"name": k, "count": v} for k, v in counts.items()],
        key=lambda x: (-x["count"], x["name"]),
    )


@app.get("/api/authors")
def api_authors():
    """Возвращает отсортированный список уникальных авторов (для автодополнения)."""
    seen: set[str] = set()
    result: list[str] = []
    for b in _library:
        author = (b.get("author") or "").strip()
        if author and author not in seen:
            seen.add(author)
            result.append(author)
    return sorted(result)


@app.get("/api/buy-list")
def api_buy_list():
    return [b for b in _library if b.get("to_buy")]


@app.post("/api/check-reading-list")
async def api_check(
    files: List[UploadFile] = File(...),
    child: str = Form(""),
    year:  str = Form(""),
):
    """Принимает одно или несколько фото списка летнего чтения."""
    reading_list: list = []
    for file in files:
        suffix = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        img_path = tmp_path
        try:
            img_path = ensure_jpeg(tmp_path)
            books = extract_books_from_photo(img_path)
            reading_list.extend(books)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            for p in set([tmp_path, img_path]):
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass

    results = check_list(reading_list, _library)
    return {
        "child":     child,
        "year":      year,
        "total":     len(reading_list),
        "found":     results["found"],
        "fuzzy":     results["fuzzy"],
        "not_found": results["not_found"],
    }


@app.post("/api/check-reading-list-text")
async def api_check_text(body: dict = Body(...)):
    """Принимает текст списка летнего чтения (вместо фото)."""
    text  = (body.get("text") or "").strip()
    child = body.get("child", "")
    year  = body.get("year", "")
    if not text:
        raise HTTPException(status_code=400, detail="Текст списка не может быть пустым")
    try:
        reading_list = extract_books_from_text(text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    results = check_list(reading_list, _library)
    return {
        "child":     child,
        "year":      year,
        "total":     len(reading_list),
        "found":     results["found"],
        "fuzzy":     results["fuzzy"],
        "not_found": results["not_found"],
    }


@app.post("/api/extract-book-cover")
async def api_extract_cover(files: List[UploadFile] = File(...)):
    """Распознаёт данные книги с фото обложки (для добавления в библиотеку)."""
    results: list = []
    for file in files:
        suffix = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        img_path = tmp_path
        try:
            img_path = ensure_jpeg(tmp_path)
            books = extract_book_info_from_photo(img_path)
            results.extend(books)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            for p in set([tmp_path, img_path]):
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass
    return results


@app.post("/api/add-book")
def api_add_book(book: dict = Body(...)):
    """Создаёт книгу в Notion и обновляет локальную библиотеку."""
    if not book.get("title", "").strip():
        raise HTTPException(status_code=400, detail="Поле title обязательно")
    try:
        create_book_in_notion(book)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    _load_library(force=True)
    return {"ok": True, "total": len(_library)}


@app.post("/api/book/set-for-whom")
def api_set_for_whom(body: dict = Body(...)):
    """Устанавливает «Для кого» у одной или нескольких книг."""
    page_ids = body.get("page_ids") or ([body["page_id"]] if body.get("page_id") else [])
    name = (body.get("name") or "").strip()
    if not page_ids or not name:
        raise HTTPException(400, "page_ids и name обязательны")
    errors = 0
    for pid in page_ids:
        try:
            set_for_whom(pid, name)
        except RuntimeError:
            errors += 1
    _load_library(force=True)
    return {"ok": True, "updated": len(page_ids) - errors, "errors": errors}


@app.post("/api/book/unbuy")
def api_unbuy(body: dict = Body(...)):
    """Снимает отметку 'Купить' у книги."""
    page_id = (body.get("page_id") or "").strip()
    if not page_id:
        raise HTTPException(status_code=400, detail="page_id обязателен")
    try:
        delete_buy_mark(page_id)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    _load_library(force=True)
    return {"ok": True}


@app.get("/api/sprints")
def api_get_sprints(child: str = "", year: int = 2026):
    try:
        return get_sprint_items(child=child, year=year)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sprints/bulk")
def api_bulk_sprint(body: dict = Body(...)):
    """Создаёт записи спринта из списка книг (все в Беклог)."""
    books  = body.get("books", [])
    child  = (body.get("child") or "").strip()
    year   = int(body.get("year") or 2026)
    status = (body.get("status") or "Беклог").strip()
    if not books:
        raise HTTPException(status_code=400, detail="books обязателен")
    if not child:
        raise HTTPException(status_code=400, detail="child обязателен")
    try:
        added = bulk_add_sprint(books, child, year, status=status)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"added": added}


@app.post("/api/sprints/add-book")
def api_sprint_add_book(body: dict = Body(...)):
    """Добавляет одну книгу из библиотеки в беклог спринта."""
    title  = (body.get("title") or "").strip()
    author = (body.get("author") or "").strip()
    child  = (body.get("child") or "").strip()
    year   = int(body.get("year") or 2026)
    if not title or not child:
        raise HTTPException(status_code=400, detail="title и child обязательны")
    try:
        added = bulk_add_sprint([{"title": title, "author": author}], child, year, status="Беклог")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"added": added}


@app.patch("/api/sprints/{item_id}")
def api_update_sprint(item_id: str, body: dict = Body(...)):
    try:
        update_sprint_item(
            item_id,
            status=body.get("status"),
            notes=body.get("notes"),
            date_read=body.get("date_read"),
            rating=body.get("rating"),
            summary=body.get("summary"),
            heroes=body.get("heroes"),
            main_idea=body.get("main_idea"),
            quote=body.get("quote"),
            questions=body.get("questions"),
            opinion=body.get("opinion"),
            genre=body.get("genre"),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.delete("/api/sprints/{item_id}")
def api_delete_sprint(item_id: str):
    try:
        delete_sprint_item(item_id)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.post("/api/refresh")
def api_refresh():
    _load_library(force=True)
    return {"total": len(_library), "source": _lib_source}


# ── Статика / SPA ─────────────────────────────────────────────────────────────
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/{full_path:path}")
def spa(full_path: str):
    return FileResponse(str(STATIC / "index.html"))


# ── Запуск ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
