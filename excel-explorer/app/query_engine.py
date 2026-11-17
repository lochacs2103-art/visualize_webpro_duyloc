"""Đọc trang CSV. DuckDB là đường chính; module csv là phương án dự phòng."""

from __future__ import annotations

import csv
import logging
import math
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.filters import FilterSpec, attach_bounds, compile_where, row_matches

logger = logging.getLogger(__name__)


def query_page(
    path: Path,
    offset: int,
    limit: int,
    spec: FilterSpec | None = None,
    total_hint: int | None = None,
    recount: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Một trang đã lọc và tổng số dòng. Không lọc thì dùng tổng đã lưu, khỏi quét cả file."""
    if not path.is_file():
        raise FileNotFoundError(path)
    where, params = compile_where(spec)
    filtered = bool(where)
    try:
        if filtered and recount:
            total = _duckdb_count(path, where, params)
        elif filtered:
            total = total_hint if total_hint is not None else _duckdb_count(path, where, params)
        else:
            total = total_hint if total_hint is not None else _duckdb_count(path, "", [])
        rows = _duckdb_page(path, offset, limit, where, params)
        return rows, total
    except Exception:
        logger.warning("DuckDB không lọc được %s, chuyển sang đọc CSV", path, exc_info=True)
        attach_bounds(path, spec)
        return _csv_query(path, offset, limit, spec, total_hint, recount)


def iter_rows(path: Path, spec: FilterSpec | None, batch: int = 2000) -> Iterator[dict[str, Any]]:
    """Duyệt mọi dòng khớp bộ lọc, từng cụm, để export không giữ cả bảng."""
    where, params = compile_where(spec)
    try:
        yield from _duckdb_iter(path, where, params, batch)
        return
    except Exception:
        logger.warning("DuckDB không xuất được %s, chuyển sang đọc CSV", path, exc_info=True)
    attach_bounds(path, spec)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            reader.fieldnames = [(name or "").lstrip("\ufeff") for name in reader.fieldnames]
        for row in reader:
            cleaned = {key: json_safe(value) for key, value in row.items()}
            if row_matches(cleaned, spec):
                yield cleaned


def read_page(path: Path, offset: int, limit: int) -> list[dict[str, Any]]:
    """Đọc một trang. Không tải cả file vào RAM khi DuckDB dùng được."""
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        return _duckdb_page(path, offset, limit)
    except Exception:
        logger.warning("DuckDB không đọc được %s, chuyển sang đọc CSV", path, exc_info=True)
        return _csv_page(path, offset, limit)


def align_rows(rows: list[dict[str, Any]], names: list[str]) -> list[dict[str, Any]]:
    """Khớp cột theo tên schema. Nếu lệch thứ tự, ghép theo vị trí."""
    aligned: list[dict[str, Any]] = []
    for row in rows:
        cleaned = {str(key).lstrip("\ufeff"): value for key, value in row.items()}
        if list(cleaned) == names:
            aligned.append({name: cleaned.get(name) for name in names})
            continue
        values = list(cleaned.values())
        aligned.append({names[index]: values[index] if index < len(values) else None for index in range(len(names))})
    return aligned


def json_safe(value: Any) -> Any:
    """Giá trị trả về API: số giữ nguyên, ngày thành ISO, còn lại là chuỗi."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value.lstrip("\ufeff")
    return str(value)


def _duckdb_page(
    path: Path,
    offset: int,
    limit: int,
    where: str = "",
    params: list[Any] | None = None,
) -> list[dict[str, Any]]:
    import duckdb

    # read_csv tự nhận BOM của UTF-8-SIG. Path dùng dấu / để tránh escape trên Windows.
    con = duckdb.connect(database=":memory:")
    try:
        cursor = con.execute(
            f"""
            WITH src AS (SELECT * FROM read_csv(?, header = true, auto_detect = true))
            SELECT * FROM src
            {where}
            LIMIT ? OFFSET ?
            """,
            [path.resolve().as_posix(), *(params or []), limit, offset],
        )
        return _records(cursor.fetchall(), cursor.description)
    finally:
        con.close()


def _duckdb_count(path: Path, where: str, params: list[Any]) -> int:
    import duckdb

    con = duckdb.connect(database=":memory:")
    try:
        cursor = con.execute(
            f"""
            WITH src AS (SELECT * FROM read_csv(?, header = true, auto_detect = true))
            SELECT count(*) FROM src {where}
            """,
            [path.resolve().as_posix(), *params],
        )
        return int(cursor.fetchone()[0])
    finally:
        con.close()


def _duckdb_iter(path: Path, where: str, params: list[Any], batch: int) -> Iterator[dict[str, Any]]:
    import duckdb

    con = duckdb.connect(database=":memory:")
    try:
        cursor = con.execute(
            f"""
            WITH src AS (SELECT * FROM read_csv(?, header = true, auto_detect = true))
            SELECT * FROM src {where}
            """,
            [path.resolve().as_posix(), *params],
        )
        while True:
            chunk = cursor.fetchmany(batch)
            if not chunk:
                break
            yield from _records(chunk, cursor.description)
    finally:
        con.close()


def _records(chunk: list[tuple], description: list[tuple]) -> list[dict[str, Any]]:
    headers = [str(column[0]).lstrip("\ufeff") for column in description]
    return [{headers[index]: json_safe(record[index]) for index in range(len(headers))} for record in chunk]


def _csv_query(
    path: Path,
    offset: int,
    limit: int,
    spec: FilterSpec | None,
    total_hint: int | None,
    recount: bool,
) -> tuple[list[dict[str, Any]], int]:
    matched: list[dict[str, Any]] = []
    total = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            reader.fieldnames = [(name or "").lstrip("\ufeff") for name in reader.fieldnames]
        for row in reader:
            cleaned = {key: json_safe(value) for key, value in row.items()}
            if not row_matches(cleaned, spec):
                continue
            if total >= offset and len(matched) < limit:
                matched.append(cleaned)
            total += 1
    if spec is None and not recount and total_hint is not None:
        total = total_hint
    return matched, total


def _csv_page(path: Path, offset: int, limit: int) -> list[dict[str, Any]]:
    """Dự phòng khi DuckDB lỗi. Trang sâu sẽ chậm vì phải bỏ qua từng dòng."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            reader.fieldnames = [(name or "").lstrip("\ufeff") for name in reader.fieldnames]
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(reader):
            if index < offset:
                continue
            if len(rows) >= limit:
                break
            rows.append({key: json_safe(value) for key, value in row.items()})
        return rows
