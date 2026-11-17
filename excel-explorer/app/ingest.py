"""Đưa file Excel vào raw/, CSV và bảng files. Dọn file dở nếu một bước lỗi."""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import RAW_DIR, from_rel, to_rel
from app.converter import SheetResult, convert_excel, parse_header_row
from app.converter_errors import ConvertError
from app.database import delete_files, get_file, insert_files, list_files
from app.filenames import safe_stem

logger = logging.getLogger(__name__)
_COPY_SUFFIX = re.compile(r"^(.+)_\d{6}(?:_\d+)?$")


def register_excel(
    source: Path,
    original_name: str,
    header_row: int,
    on_progress: Callable[[int, str], None] | None = None,
) -> list[dict[str, Any]]:
    """Giữ bản gốc, ghi CSV, rồi mới đăng ký SQLite."""
    raw_path: Path | None = None
    sheets: list[SheetResult] = []
    try:
        header = parse_header_row(header_row)
        stem = safe_stem(Path(original_name).stem)
        ext = source.suffix.lower()
        if ext not in {".xlsx", ".xls"}:
            raise ConvertError("bad_type")
        date_folder = datetime.now().strftime("%Y-%m-%d")
        forget_workbook(stem)
        raw_path = RAW_DIR / date_folder / f"{stem}{ext}"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if on_progress is not None:
            on_progress(8, original_name)
        shutil.copy2(source, raw_path)
        sheets = convert_excel(
            raw_path,
            stem,
            header,
            date_folder,
            None if on_progress is None else (lambda pct, detail: on_progress(10 + int(pct * 0.85), detail)),
        )
        return _insert(sheets, raw_path, date_folder)
    except ConvertError:
        _cleanup(raw_path, sheets)
        raise
    except Exception as exc:
        _cleanup(raw_path, sheets)
        logger.exception("Nạp Excel thất bại: %s", original_name)
        raise ConvertError("bad_excel") from exc


def _insert(sheets: list[SheetResult], raw_path: Path, date_folder: str) -> list[dict[str, Any]]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    original = to_rel(raw_path)
    rows = [
        {
            "name": sheet.display_name,
            "original_path": original,
            "csv_path": to_rel(sheet.csv_path),
            "date_folder": date_folder,
            "row_count": sheet.row_count,
            "col_count": sheet.col_count,
            "schema_json": json.dumps(sheet.schema, ensure_ascii=False),
            "uploaded_at": now,
        }
        for sheet in sheets
    ]
    records: list[dict[str, Any]] = []
    for file_id in insert_files(rows):
        record = get_file(file_id)
        if record is not None:
            records.append(record)
    logger.info("Đã nạp %s sheet từ %s", len(records), raw_path.name)
    return records


def remove_library_file(file_id: int) -> bool:
    """Xóa một file thư viện: mọi sheet cùng file gốc, bản CSV, và file Excel nếu không còn ai dùng."""
    record = get_file(file_id)
    if record is None:
        return False
    original = str(record.get("original_path") or "")
    if original:
        rows = [row for row in list_files() if str(row.get("original_path") or "") == original]
    else:
        rows = [record]
    if not rows:
        rows = [record]
    paths: list[str] = []
    for row in rows:
        for key in ("csv_path", "parquet_path", "original_path"):
            rel = str(row.get(key) or "")
            if rel and rel not in paths:
                paths.append(rel)
    delete_files([int(row["id"]) for row in rows])
    used: set[str] = set()
    for row in list_files():
        for key in ("csv_path", "parquet_path", "original_path"):
            rel = str(row.get(key) or "")
            if rel:
                used.add(rel)
    for rel in paths:
        if rel not in used:
            _unlink_rel(rel)
    logger.info("Đã xóa file thư viện %s (%s bản)", file_id, len(rows))
    return True


def forget_workbook(stem: str) -> None:
    """Nạp lại cùng một file thì bỏ bản cũ, kể cả bản đã thêm giờ phút."""
    doomed = [row for row in list_files() if _same_stem(Path(str(row.get("original_path") or "")).stem, stem)]
    seen: set[str] = set()
    for row in doomed:
        for key in ("csv_path", "parquet_path"):
            _unlink_rel(row.get(key))
        raw = row.get("original_path")
        if raw and raw not in seen:
            seen.add(raw)
            _unlink_rel(raw)
    delete_files([int(row["id"]) for row in doomed])


def _same_stem(stored: str, stem: str) -> bool:
    if stored == stem:
        return True
    match = _COPY_SUFFIX.match(stored)
    return bool(match and match.group(1) == stem)


def _unlink_rel(rel: str | None) -> None:
    if not rel:
        return
    try:
        from_rel(rel).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.warning("Không xóa được %s", rel, exc_info=True)


def _cleanup(raw_path: Path | None, sheets: list[SheetResult]) -> None:
    for sheet in sheets:
        sheet.csv_path.unlink(missing_ok=True)
    if raw_path is not None:
        raw_path.unlink(missing_ok=True)
