"""Chuẩn hoá ô Excel và đoán kiểu cột từ một mẫu nhỏ."""

from __future__ import annotations

import math
from datetime import date, datetime


def cell_to_text(value: object) -> str:
    """Giá trị ghi ra CSV: ngày ISO, số không dạng khoa học, ô trống thành chuỗi rỗng."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        if value.hour == value.minute == value.second == value.microsecond == 0:
            return value.date().isoformat()
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)


def suggest_header_row(rows: list[list[str]]) -> int:
    """Dòng đầu tiên có nhiều chữ hơn số được coi là dòng tiêu đề."""
    for index, row in enumerate(rows, start=1):
        cells = [cell.strip() for cell in row if cell and cell.strip()]
        if len(cells) < 2:
            continue
        labels = sum(1 for cell in cells if not _looks_number(cell))
        if labels * 2 >= len(cells):
            return index
    return 1


def headers_from_row(values: list[object]) -> list[str]:
    trimmed = trim_trailing_empty(values)
    if not trimmed:
        return ["column_1"]
    texts = []
    for index, value in enumerate(trimmed):
        text = " ".join(cell_to_text(value).split())
        texts.append(text or f"column_{index + 1}")
    return dedupe(texts)


def pandas_headers(columns: list[object]) -> list[str]:
    texts = []
    for index, column in enumerate(columns):
        text = " ".join(str(column).split())
        if not text or text.startswith("Unnamed:"):
            text = f"column_{index + 1}"
        texts.append(text)
    return dedupe(texts)


def guess_type(samples: list[object]) -> str:
    if not samples:
        return "text"
    if all(isinstance(value, (datetime, date)) and not isinstance(value, bool) for value in samples):
        return "date"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in samples):
        return "number"
    return "text"


def pandas_type(dtype: object) -> str:
    name = str(dtype)
    if "datetime" in name or name.startswith("date"):
        return "date"
    if any(token in name for token in ("int", "float", "double", "decimal")):
        return "number"
    return "text"


def collect_samples(samples: list[list[object]], values: list[object]) -> None:
    for index, value in enumerate(values):
        if not is_blank(value):
            samples[index].append(value)


def trim_trailing_empty(values: list[object]) -> list[object]:
    end = len(values)
    while end > 0 and is_blank(values[end - 1]):
        end -= 1
    return values[:end]


def is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and not math.isfinite(value):
        return True
    return str(value).strip() == ""


def dedupe(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return result or ["column_1"]


def _looks_number(text: str) -> bool:
    token = text.strip().replace(" ", "").replace(",", ".")
    if not token:
        return False
    try:
        float(token)
    except ValueError:
        return False
    return True
