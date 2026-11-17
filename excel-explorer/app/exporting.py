"""Xuất kết quả đang lọc ra CSV, Excel hoặc JSON. Ghi theo dòng, không gom cả bảng."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from openpyxl import Workbook


def iter_csv(columns: list[str], rows: Iterator[list[Any]]) -> Iterator[bytes]:
    yield "\ufeff".encode("utf-8")
    yield _csv_line(columns)
    for row in rows:
        yield _csv_line(["" if value is None else value for value in row])


def iter_json(columns: list[str], rows: Iterator[list[Any]]) -> Iterator[bytes]:
    yield b"["
    first = True
    for row in rows:
        payload = json.dumps({columns[index]: row[index] for index in range(len(columns))}, ensure_ascii=False)
        if first:
            yield payload.encode("utf-8")
            first = False
        else:
            yield ("," + payload).encode("utf-8")
    yield b"]"


def write_xlsx(dest: Path, columns: list[str], rows: Iterator[list[Any]]) -> None:
    book = Workbook(write_only=True)
    sheet = book.create_sheet("export")
    sheet.append(columns)
    for row in rows:
        sheet.append([_excel_value(value) for value in row])
    book.save(dest)


def _csv_line(values: list[Any]) -> bytes:
    import io

    buffer = io.StringIO()
    csv.writer(buffer).writerow(values)
    return buffer.getvalue().encode("utf-8")


def _excel_value(value: Any) -> Any:
    if value is None or value == "":
        return None
    return value
