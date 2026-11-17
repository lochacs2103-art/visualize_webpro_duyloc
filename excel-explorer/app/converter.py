"""Excel → CSV UTF-8-SIG.

.xlsx đọc từng dòng bằng openpyxl read_only, không gom cả sheet vào RAM.
.xls không có API streaming nên đi qua pandas + xlrd.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.cells import (
    cell_to_text,
    collect_samples,
    guess_type,
    headers_from_row,
    pandas_headers,
    pandas_type,
)
from app.config import CSV_DIR, MAX_HEADER_ROW
from app.converter_errors import ConvertError
from app.filenames import safe_stem

_SAMPLE_LIMIT = 200
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SheetResult:
    display_name: str
    sheet: str
    csv_path: Path
    row_count: int
    col_count: int
    schema: list[dict[str, str]] = field(default_factory=list)


class _SkipSheet(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def parse_header_row(value: int) -> int:
    if value < 1 or value > MAX_HEADER_ROW:
        raise ConvertError("bad_header")
    return value


def convert_excel(
    path: Path,
    stem: str,
    header_row: int,
    date_folder: str,
    on_progress: Callable[[int, str], None] | None = None,
) -> list[SheetResult]:
    """Ghi CSV vào data/csv/YYYY-MM-DD. Một sheet giữ tên file; nhiều sheet thêm tên sheet."""
    header_row = parse_header_row(header_row)
    folder = CSV_DIR / date_folder
    folder.mkdir(parents=True, exist_ok=True)
    reserved = _reserve_stem(folder, stem)
    suffix = path.suffix.lower()
    results: list[SheetResult] = []
    try:
        if suffix == ".xls":
            results = _convert_xls(path, reserved, header_row, folder, on_progress)
        elif suffix == ".xlsx":
            results = _convert_xlsx(path, reserved, header_row, folder, on_progress)
        else:
            raise ConvertError("bad_type")
        if len(results) == 1:
            _rename_single(results[0], folder, reserved)
        else:
            for item in results:
                item.display_name = f"{reserved} — {item.sheet}"
        return results
    except Exception:
        for item in results:
            item.csv_path.unlink(missing_ok=True)
        raise


def _convert_xlsx(
    path: Path,
    reserved: str,
    header_row: int,
    folder: Path,
    on_progress: Callable[[int, str], None] | None = None,
) -> list[SheetResult]:
    written: list[Path] = []
    results: list[SheetResult] = []
    short = 0
    try:
        workbook = load_workbook(filename=path, read_only=True, data_only=True)
    except Exception as exc:
        raise ConvertError("bad_excel") from exc
    try:
        sheets = list(workbook.worksheets)
        total = max(1, len(sheets))
        for index, worksheet in enumerate(sheets, start=1):
            dest = _sheet_path(folder, reserved, worksheet.title, index)
            base = int(100 * (index - 1) / total)
            span = max(1, int(100 / total))

            def on_rows(count: int, title: str = worksheet.title, start: int = base, width: int = span) -> None:
                if on_progress is None:
                    return
                filled = min(width - 1, max(1, count // 2000))
                on_progress(min(99, start + filled), f"{title} · {count}")

            try:
                result = _write_xlsx_sheet(worksheet, dest, header_row, on_rows)
            except _SkipSheet as skip:
                dest.unlink(missing_ok=True)
                if skip.reason == "short":
                    short += 1
                    logger.warning("Bỏ qua sheet %s vì dòng tiêu đề %s vượt quá sheet", worksheet.title, header_row)
                continue
            except Exception:
                dest.unlink(missing_ok=True)
                raise
            written.append(result.csv_path)
            results.append(result)
    except Exception:
        for item in written:
            item.unlink(missing_ok=True)
        raise
    finally:
        workbook.close()
    if not results:
        raise ConvertError("header_past_end" if short else "empty_file")
    return results


def _write_xlsx_sheet(
    worksheet: Any,
    dest: Path,
    header_row: int,
    on_rows: Callable[[int], None] | None = None,
) -> SheetResult:
    header: list[str] | None = None
    samples: list[list[object]] = []
    row_count = 0
    seen = 0
    with dest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        for raw in worksheet.iter_rows(values_only=True):
            values = list(raw or [])
            seen += 1
            if header is None:
                if seen < header_row:
                    continue
                header = headers_from_row(values)
                samples = [[] for _ in header]
                writer.writerow(header)
                continue
            width = len(header)
            padded = values[:width] + [None] * max(0, width - len(values))
            writer.writerow([cell_to_text(value) for value in padded])
            row_count += 1
            if on_rows is not None and row_count % 2000 == 0:
                on_rows(row_count)
            if row_count <= _SAMPLE_LIMIT:
                collect_samples(samples, padded)
    if on_rows is not None and row_count:
        on_rows(row_count)
    if header is None:
        dest.unlink(missing_ok=True)
        raise _SkipSheet("short" if seen else "empty")
    schema = [{"name": header[i], "type": guess_type(samples[i])} for i in range(len(header))]
    return SheetResult(worksheet.title, worksheet.title, dest, row_count, len(header), schema)


def _convert_xls(
    path: Path,
    reserved: str,
    header_row: int,
    folder: Path,
    on_progress: Callable[[int, str], None] | None = None,
) -> list[SheetResult]:
    import pandas as pd

    written: list[Path] = []
    try:
        book = pd.ExcelFile(path, engine="xlrd")
        try:
            frames = [(str(name), book.parse(sheet_name=name, header=header_row - 1)) for name in book.sheet_names]
        finally:
            book.close()
    except Exception as exc:
        message = str(exc).lower()
        if "header" in message or "out of bounds" in message:
            raise ConvertError("header_past_end") from exc
        raise ConvertError("bad_excel") from exc
    usable = [(name, frame) for name, frame in frames if frame.shape[1] > 0]
    if not usable:
        raise ConvertError("empty_file")
    results: list[SheetResult] = []
    try:
        for index, (name, frame) in enumerate(usable, start=1):
            if on_progress is not None:
                on_progress(int(100 * (index - 1) / max(1, len(usable))), name)
            dest = _sheet_path(folder, reserved, name, index)
            result = _write_frame(frame, dest, name)
            written.append(dest)
            results.append(result)
    except Exception:
        for item in written:
            item.unlink(missing_ok=True)
        raise
    return results


def _write_frame(frame: Any, dest: Path, sheet: str) -> SheetResult:
    headers = pandas_headers(list(frame.columns))
    data = frame.copy()
    data.columns = headers
    data.to_csv(dest, index=False, encoding="utf-8-sig")
    schema = [{"name": headers[i], "type": pandas_type(data.dtypes.iloc[i])} for i in range(len(headers))]
    return SheetResult(sheet, sheet, dest, int(len(data)), len(headers), schema)


def _rename_single(result: SheetResult, folder: Path, reserved: str) -> None:
    desired = folder / f"{reserved}.csv"
    if result.csv_path != desired and not desired.exists():
        result.csv_path.rename(desired)
        result.csv_path = desired
    result.display_name = result.csv_path.stem


def _reserve_stem(folder: Path, stem: str) -> str:
    """Cùng tên trong một ngày: thêm _HHMMSS, dùng chung cho mọi sheet của lần nạp."""

    def taken(name: str) -> bool:
        if (folder / f"{name}.csv").exists():
            return True
        return any(folder.glob(f"{name}__*.csv"))

    if not taken(stem):
        return stem
    stamp = datetime.now().strftime("%H%M%S")
    candidate = f"{stem}_{stamp}"
    if not taken(candidate):
        return candidate
    for number in range(2, 1000):
        candidate = f"{stem}_{stamp}_{number}"
        if not taken(candidate):
            return candidate
    raise ConvertError("bad_excel")


def _sheet_path(folder: Path, reserved: str, sheet: str, index: int) -> Path:
    slug = safe_stem(sheet, "sheet")
    dest = folder / f"{reserved}__{slug}.csv"
    if dest.exists():
        dest = folder / f"{reserved}__{slug}_{index}.csv"
    return dest
