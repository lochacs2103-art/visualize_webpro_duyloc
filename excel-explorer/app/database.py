"""SQLite: khởi tạo schema và đăng ký file đã convert."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.config import DB_PATH, ensure_dirs
from app.models import SCHEMA_SQL

logger = logging.getLogger(__name__)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Một connection cho mỗi thao tác, đóng ngay để không khoá file khi thoát app."""
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Tạo bảng nếu chưa có, kể cả FTS5 (index nội dung làm ở phase sau)."""
    with connect() as conn:
        conn.executescript(SCHEMA_SQL)
        _ensure_column(conn, "column_prefs", "show_colors", "INTEGER DEFAULT 0")
    logger.info("SQLite sẵn sàng tại %s", DB_PATH)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    found = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in found:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def insert_files(rows: list[dict[str, Any]]) -> list[int]:
    """Ghi nhiều sheet trong một transaction. `csv_path` là đường dẫn tương đối."""
    sql = """
        INSERT INTO files (
            name, original_path, csv_path, parquet_path, date_folder,
            row_count, col_count, schema_json, uploaded_at
        ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)
    """
    ids: list[int] = []
    with connect() as conn:
        for row in rows:
            cursor = conn.execute(
                sql,
                (
                    row["name"],
                    row.get("original_path"),
                    row["csv_path"],
                    row["date_folder"],
                    row.get("row_count"),
                    row.get("col_count"),
                    row.get("schema_json"),
                    row["uploaded_at"],
                ),
            )
            ids.append(int(cursor.lastrowid))
    _forget_home()
    return ids


def get_file(file_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    return dict(row) if row else None


def list_files() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM files
            ORDER BY date_folder DESC, uploaded_at DESC, name COLLATE NOCASE ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def workbook_name(record: dict[str, Any]) -> str:
    """Tên file Excel người dùng đã mở, không phải tên từng sheet."""
    original = record.get("original_path") or ""
    if original:
        return Path(original).name
    name = str(record.get("name") or "file")
    if " — " in name:
        return name.split(" — ", 1)[0]
    return name


def list_tree() -> list[dict[str, Any]]:
    """Một dòng cho mỗi file Excel. Nhiều sheet nằm trong file đó."""
    groups: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for item in list_files():
        key = (str(item.get("date_folder") or ""), str(item.get("original_path") or item["csv_path"]))
        book = seen.get(key)
        rows = int(item.get("row_count") or 0)
        if book is None:
            book = {
                "id": item["id"],
                "name": workbook_name(item),
                "date_folder": item["date_folder"],
                "row_count": rows,
                "col_count": int(item.get("col_count") or 0),
                "sheet_count": 0,
            }
            seen[key] = book
            bucket = index.get(book["date_folder"])
            if bucket is None:
                bucket = {"date": book["date_folder"], "files": []}
                index[book["date_folder"]] = bucket
                groups.append(bucket)
            bucket["files"].append(book)
        book["sheet_count"] += 1
        if rows > int(book["row_count"] or 0):
            book["id"] = item["id"]
            book["row_count"] = rows
            book["col_count"] = int(item.get("col_count") or 0)
    return groups


def sheets_in(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Các sheet của cùng file Excel, theo thứ tự nạp."""
    original = record.get("original_path")
    with connect() as conn:
        if original:
            rows = conn.execute(
                "SELECT id, name FROM files WHERE original_path = ? ORDER BY id",
                (original,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT id, name FROM files WHERE id = ?", (record["id"],)).fetchall()
    sheets: list[dict[str, Any]] = []
    for row in rows:
        name = str(row["name"])
        label = name.split(" — ", 1)[1] if " — " in name else name
        sheets.append({"id": row["id"], "label": label, "current": row["id"] == record["id"]})
    return sheets


def delete_files(ids: list[int]) -> None:
    if not ids:
        return
    with connect() as conn:
        conn.executemany("DELETE FROM files_fts WHERE file_id = ?", [(item,) for item in ids])
        conn.executemany("DELETE FROM files WHERE id = ?", [(item,) for item in ids])
    _forget_home()


def _forget_home() -> None:
    """Xoá cache trang chủ sau khi thư viện đổi. Import muộn để tránh vòng."""
    from app.homeboard import invalidate

    invalidate()


def parse_schema(record: dict[str, Any]) -> list[dict[str, str]]:
    """Đọc schema_json thành danh sách {name, type}."""
    try:
        parsed = json.loads(record.get("schema_json") or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    columns: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        columns.append({"name": str(item["name"]), "type": str(item.get("type") or "text")})
    return columns
