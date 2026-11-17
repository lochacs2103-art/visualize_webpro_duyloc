"""Trang chủ: thống kê, file gần đây, cột hay gặp. Đọc SQLite, cache 30 giây."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.config import from_rel
from app.database import connect, parse_schema, workbook_name

_TTL = 30.0
_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cached_at = 0.0


def invalidate() -> None:
    """Bỏ cache khi thư viện thêm hoặc xoá file."""
    global _cache, _cached_at
    with _lock:
        _cache = None
        _cached_at = 0.0


def board() -> dict[str, Any]:
    """Snapshot dùng cho HTML và cho API. Không query lại trong 30 giây."""
    global _cache, _cached_at
    now = time.monotonic()
    with _lock:
        if _cache is not None and now - _cached_at < _TTL:
            return _cache
    data = _build()
    with _lock:
        _cache = data
        _cached_at = time.monotonic()
    return data


def stats() -> dict[str, Any]:
    return board()["stats"]


def recent_files() -> list[dict[str, Any]]:
    return board()["recent"]


def _build() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM files ORDER BY uploaded_at DESC, id DESC"
        ).fetchall()
    books = _workbooks([dict(row) for row in rows])
    latest = books[0]["uploaded_at"] if books else ""
    total_rows = sum(int(book["row_sum"]) for book in books)
    total_bytes = sum(int(book["bytes"]) for book in books)
    columns = _common_columns(books)
    recent = [_public_book(book) for book in books[:6]]
    return {
        "stats": {
            "files": len(books),
            "rows": total_rows,
            "bytes": total_bytes,
            "size": _format_bytes(total_bytes),
            "latest": latest,
        },
        "recent": recent,
        "columns": columns,
        "columns_json": json.dumps(columns, ensure_ascii=False).replace("<", "\\u003c"),
    }


def _workbooks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Một workbook cho mỗi file gốc. Dòng đầu trong `rows` là bản mới nhất."""
    order: list[dict[str, Any]] = []
    found: dict[str, dict[str, Any]] = {}
    for item in rows:
        key = str(item.get("original_path") or item["csv_path"])
        book = found.get(key)
        count = int(item.get("row_count") or 0)
        if book is None:
            book = {
                "id": item["id"],
                "name": workbook_name(item),
                "sheet_count": 0,
                "row_count": count,
                "col_count": int(item.get("col_count") or 0),
                "row_sum": 0,
                "bytes": 0,
                "uploaded_at": str(item.get("uploaded_at") or ""),
                "columns": set(),
            }
            found[key] = book
            order.append(book)
        book["sheet_count"] += 1
        book["row_sum"] += count
        book["bytes"] += _csv_size(item.get("csv_path") or "")
        if count > int(book["row_count"]):
            book["id"] = item["id"]
            book["row_count"] = count
            book["col_count"] = int(item.get("col_count") or 0)
        for column in parse_schema(item):
            book["columns"].add(column["name"])
    return order


def _public_book(book: dict[str, Any]) -> dict[str, Any]:
    name = str(book["name"])
    kind = "csv" if name.lower().endswith(".csv") else "xlsx"
    return {
        "id": book["id"],
        "name": name,
        "sheet_count": book["sheet_count"],
        "row_count": book["row_count"],
        "col_count": book["col_count"],
        "uploaded_at": book["uploaded_at"],
        "kind": kind,
    }


def _common_columns(books: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tên cột gặp ở nhiều file gốc nhất. Một file chỉ tính một lần."""
    counts: dict[str, dict[str, Any]] = {}
    for book in books:
        for name in book["columns"]:
            entry = counts.get(name)
            if entry is None:
                entry = {"name": name, "count": 0, "files": []}
                counts[name] = entry
            entry["count"] += 1
            entry["files"].append({"id": book["id"], "name": book["name"]})
    ranked = sorted(counts.values(), key=lambda item: (-item["count"], item["name"].casefold()))
    return ranked[:10]


def _csv_size(rel: str) -> int:
    try:
        return from_rel(rel).stat().st_size
    except (OSError, ValueError):
        return 0


def _format_bytes(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
