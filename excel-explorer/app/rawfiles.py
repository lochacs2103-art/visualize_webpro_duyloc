"""File Excel để nguyên, chưa đưa vào thư viện."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.cells import cell_to_text, headers_from_row, trim_trailing_empty
from app.config import RAW_UPLOADS_DIR, from_rel, to_rel
from app.converter_errors import ConvertError
from app.database import connect
from app.filenames import safe_stem, unique_path


def save_upload(name: str, payload: bytes) -> dict[str, Any]:
    ext = Path(name).suffix.lower()
    if ext not in {".xlsx", ".xls"}:
        raise ConvertError("bad_type")
    day = datetime.now().strftime("%Y-%m-%d")
    folder = RAW_UPLOADS_DIR / day
    dest = unique_path(folder, safe_stem(Path(name).stem), ext)
    dest.write_bytes(payload)
    sheets = sheet_names(dest)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO raw_files (name, path, size_bytes, sheet_names_json, uploaded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (dest.name, to_rel(dest), dest.stat().st_size, json.dumps(sheets, ensure_ascii=False), now),
        )
        row_id = int(cursor.lastrowid)
    return get_raw(row_id) or {}


def list_raw() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM raw_files ORDER BY uploaded_at DESC, id DESC").fetchall()
    return [_public(dict(row)) for row in rows]


def get_raw(raw_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM raw_files WHERE id = ?", (raw_id,)).fetchone()
    return _public(dict(row)) if row else None


def delete_raw(raw_id: int) -> None:
    record = get_raw(raw_id)
    if record is None:
        return
    try:
        from_rel(record["path"]).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass
    with connect() as conn:
        conn.execute("DELETE FROM raw_files WHERE id = ?", (raw_id,))


def sheet_names(path: Path) -> list[str]:
    if path.suffix.lower() == ".xls":
        import pandas as pd

        book = pd.ExcelFile(path, engine="xlrd")
        try:
            return [str(name) for name in book.sheet_names]
        finally:
            book.close()
    workbook = load_workbook(filename=path, read_only=True, data_only=True)
    try:
        return [sheet.title for sheet in workbook.worksheets]
    finally:
        workbook.close()


def header_names(path: Path, sheet: str, header_row: int) -> list[str]:
    """Chỉ đọc dòng tiêu đề, không convert cả sheet."""
    header_row = max(1, min(100, header_row))
    if path.suffix.lower() == ".xls":
        import pandas as pd

        frame = pd.read_excel(path, sheet_name=sheet, header=None, nrows=header_row, engine="xlrd")
        if frame.shape[0] < header_row:
            raise ConvertError("header_past_end")
        return headers_from_row(list(frame.iloc[header_row - 1].tolist()))
    workbook = load_workbook(filename=path, read_only=True, data_only=True)
    try:
        worksheet = _worksheet(workbook, sheet)
        seen = 0
        for raw in worksheet.iter_rows(values_only=True):
            seen += 1
            if seen == header_row:
                return headers_from_row(list(raw or []))
        raise ConvertError("header_past_end")
    finally:
        workbook.close()


def peek_sheet(path: Path, sheet: str, limit: int = 10) -> list[list[str]]:
    if path.suffix.lower() == ".xls":
        import pandas as pd

        frame = pd.read_excel(path, sheet_name=sheet, header=None, nrows=limit, engine="xlrd")
        rows = []
        for values in frame.itertuples(index=False, name=None):
            rows.append([cell_to_text(value) for value in trim_trailing_empty(list(values))])
        return rows
    workbook = load_workbook(filename=path, read_only=True, data_only=True)
    try:
        worksheet = _worksheet(workbook, sheet)
        rows = []
        for index, raw in enumerate(worksheet.iter_rows(values_only=True)):
            if index >= limit:
                break
            rows.append([cell_to_text(value) for value in trim_trailing_empty(list(raw or []))])
        return rows
    finally:
        workbook.close()


def _worksheet(workbook: Any, sheet: str) -> Any:
    for item in workbook.worksheets:
        if item.title == sheet:
            return item
    raise ConvertError("empty_file")


def _public(row: dict[str, Any]) -> dict[str, Any]:
    try:
        sheets = json.loads(row.get("sheet_names_json") or "[]")
    except json.JSONDecodeError:
        sheets = []
    row["sheets"] = sheets if isinstance(sheets, list) else []
    row["size_label"] = _size(int(row.get("size_bytes") or 0))
    return row


def _size(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
