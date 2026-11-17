"""Đọc vài dòng đầu của Excel để người dùng chọn dòng tiêu đề."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.cells import cell_to_text, suggest_header_row, trim_trailing_empty
from app.converter_errors import ConvertError


def peek_excel(path: Path, limit: int = 10) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".xls":
        return _peek_xls(path, limit)
    if suffix == ".xlsx":
        return _peek_xlsx(path, limit)
    raise ConvertError("bad_type")


def _peek_xlsx(path: Path, limit: int) -> dict[str, Any]:
    try:
        workbook = load_workbook(filename=path, read_only=True, data_only=True)
    except Exception as exc:
        raise ConvertError("bad_excel") from exc
    try:
        sheets = workbook.worksheets
        if not sheets:
            raise ConvertError("empty_file")
        rows: list[list[str]] = []
        for index, raw in enumerate(sheets[0].iter_rows(values_only=True)):
            if index >= limit:
                break
            values = trim_trailing_empty(list(raw or []))
            rows.append([cell_to_text(value) for value in values])
        if not any(any(cell.strip() for cell in row) for row in rows):
            raise ConvertError("empty_file")
        return _payload(sheets[0].title, len(sheets), rows)
    finally:
        workbook.close()


def _peek_xls(path: Path, limit: int) -> dict[str, Any]:
    import pandas as pd

    try:
        book = pd.ExcelFile(path, engine="xlrd")
        try:
            names = list(book.sheet_names)
            if not names:
                raise ConvertError("empty_file")
            frame = book.parse(sheet_name=names[0], header=None, nrows=limit)
        finally:
            book.close()
    except ConvertError:
        raise
    except Exception as exc:
        raise ConvertError("bad_excel") from exc
    rows = _frame_rows(frame)
    if not rows:
        raise ConvertError("empty_file")
    return _payload(str(names[0]), len(names), rows)


def _payload(sheet: str, sheet_count: int, rows: list[list[str]]) -> dict[str, Any]:
    width = max((len(row) for row in rows), default=0)
    padded = [row + [""] * (width - len(row)) for row in rows]
    return {
        "sheet": sheet,
        "sheet_count": sheet_count,
        "rows": padded,
        "suggested": suggest_header_row(padded),
    }


def _frame_rows(frame: Any) -> list[list[str]]:
    import pandas as pd

    rows: list[list[str]] = []
    for record in frame.itertuples(index=False, name=None):
        rows.append(["" if pd.isna(value) else cell_to_text(value) for value in record])
    kept = [row for row in rows if any(cell.strip() for cell in row)]
    return kept or rows
