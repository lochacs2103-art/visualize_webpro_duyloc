"""Trang thư viện và bảng dữ liệu."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.config import HOVER_ROWS, from_rel
from app.database import get_file, list_tree, parse_schema, sheets_in, workbook_name
from app.ingest import remove_library_file
from app.filters import FilterError, parse_filter
from app.present import library_context
from app.query_engine import align_rows, query_page, read_page
from app.templating import render

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/")
def home(request: Request):
    return render(request, "explorer.html", library_context())


@router.get("/files")
def files() -> list[dict]:
    return list_tree()


@router.get("/files/{file_id}/preview")
def preview(file_id: int):
    record = get_file(file_id)
    if record is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    columns = [column["name"] for column in parse_schema(record)]
    try:
        page = align_rows(read_page(from_rel(record["csv_path"]), 0, HOVER_ROWS), columns)
    except (OSError, ValueError):
        logger.warning("Không xem trước được file %s", file_id, exc_info=True)
        return {"columns": columns, "rows": []}
    rows = [["" if row.get(name) is None else str(row.get(name)) for name in columns] for row in page]
    return {"columns": columns, "rows": rows}


@router.get("/files/{file_id}/rows")
def file_rows(file_id: int, offset: int = 0, limit: int = 80, filter: str = "", recount: int = 1, total: int = -1):
    record = get_file(file_id)
    if record is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    offset = max(0, offset)
    limit = min(max(1, limit), 200)
    schema = parse_schema(record)
    names = [column["name"] for column in schema]
    try:
        spec = parse_filter(filter, schema)
        stored = int(record.get("row_count") or 0)
        hint = stored if spec is None else (total if total >= 0 else None)
        page, count = query_page(from_rel(record["csv_path"]), offset, limit, spec, hint, bool(recount) or hint is None)
        aligned = align_rows(page, names)
    except FilterError:
        return JSONResponse({"detail": "bad_filter"}, status_code=400)
    except (OSError, ValueError):
        logger.warning("Không đọc được CSV của file %s", file_id, exc_info=True)
        aligned, count = [], 0
    matrix = [["" if item.get(name) is None else item.get(name) for name in names] for item in aligned]
    return {"columns": names, "rows": matrix, "offset": offset, "total": count}


@router.delete("/files/{file_id}")
def remove_file(file_id: int):
    if not remove_library_file(file_id):
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return Response(status_code=204, headers={"HX-Redirect": "/"})


@router.get("/files/{file_id}")
def viewer(request: Request, file_id: int):
    record = get_file(file_id)
    if record is None:
        return render(request, "error.html", {"message_key": "not_found"}, status_code=404)
    csv_path = record.get("csv_path") or ""
    try:
        path = from_rel(csv_path)
        if not path.is_file():
            raise FileNotFoundError(path)
    except (OSError, ValueError):
        logger.warning("CSV mất hoặc hỏng: %s", csv_path, exc_info=True)
        return render(request, "error.html", {"message_key": "missing_csv", "file": record}, status_code=404)
    return render(
        request,
        "viewer.html",
        {
            "file": record,
            "workbook": workbook_name(record),
            "sheets": sheets_in(record),
            "schema": parse_schema(record),
            "total": int(record.get("row_count") or 0),
        },
    )
