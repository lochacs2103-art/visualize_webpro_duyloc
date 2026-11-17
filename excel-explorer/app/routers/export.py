"""Tải kết quả đang xem. Có bộ lọc thì thêm hậu tố _filtered."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from app.config import STAGING_DIR, from_rel
from app.database import get_file, parse_schema, workbook_name
from app.exporting import iter_csv, iter_json, write_xlsx
from app.filenames import safe_stem
from app.filters import FilterError, parse_filter
from app.query_engine import align_rows, iter_rows

logger = logging.getLogger(__name__)
router = APIRouter()

_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json; charset=utf-8",
}


@router.get("/files/{file_id}/export")
def export_sheet(file_id: int, fmt: str = Query(default="csv", alias="format"), filter: str = ""):
    record = get_file(file_id)
    if record is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    if fmt not in _TYPES:
        return JSONResponse({"detail": "bad_format"}, status_code=400)
    schema = parse_schema(record)
    names = [column["name"] for column in schema]
    try:
        spec = parse_filter(filter, schema)
        path = from_rel(record.get("csv_path") or "")
        if not path.is_file():
            raise FileNotFoundError(path)
    except FilterError:
        return JSONResponse({"detail": "bad_filter"}, status_code=400)
    except (OSError, ValueError):
        return JSONResponse({"detail": "missing_csv"}, status_code=404)
    filename = _filename(record, bool(spec), fmt)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    matrix = _matrix(path, spec, names)
    if fmt == "xlsx":
        dest = STAGING_DIR / f"{uuid4().hex}.xlsx"
        try:
            write_xlsx(dest, names, matrix)
        except Exception:
            dest.unlink(missing_ok=True)
            logger.exception("Xuất Excel thất bại: %s", file_id)
            return JSONResponse({"detail": "bad_excel"}, status_code=500)
        return FileResponse(dest, media_type=_TYPES[fmt], headers=headers, background=BackgroundTask(dest.unlink, missing_ok=True))
    stream = iter_csv(names, matrix) if fmt == "csv" else iter_json(names, matrix)
    return StreamingResponse(stream, media_type=_TYPES[fmt], headers=headers)


def _matrix(path: Path, spec, names: list[str]):
    for row in iter_rows(path, spec):
        aligned = align_rows([row], names)[0]
        yield [aligned.get(name) for name in names]


def _filename(record: dict, filtered: bool, fmt: str) -> str:
    label = str(record.get("name") or workbook_name(record))
    if " — " in label:
        stem, sheet = label.split(" — ", 1)
        base = f"{stem}_{sheet}"
    else:
        base = Path(label).stem
    suffix = "_filtered" if filtered else ""
    return f"{safe_stem(base)}{suffix}.{fmt}"
