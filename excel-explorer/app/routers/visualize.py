"""Chart, màu ô, thông tin cột và pivot. Không đụng mapping."""

from __future__ import annotations

import logging
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from app.analysis import AnalysisError, column_profile, delete_pivot, list_pivots, pivot_table, save_pivot
from app.charts import (
    ChartError,
    chart_payload,
    delete_chart,
    list_charts,
    number_bounds,
    save_chart,
    set_show_colors,
    show_colors,
)
from app.config import STAGING_DIR, from_rel
from app.database import get_file, parse_schema
from app.exporting import iter_csv, write_xlsx

logger = logging.getLogger(__name__)
router = APIRouter()


def _record(file_id: int):
    record = get_file(file_id)
    if record is None:
        return None, None
    try:
        path = from_rel(record["csv_path"])
    except (OSError, ValueError):
        return record, None
    if not path.is_file():
        return record, None
    return record, path


@router.post("/files/{file_id}/chart-data")
async def chart_data(file_id: int, request: Request):
    record, path = _record(file_id)
    if record is None or path is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "bad_chart"}, status_code=400)
    try:
        return chart_payload(path, parse_schema(record), body if isinstance(body, dict) else {})
    except ChartError:
        return JSONResponse({"detail": "bad_chart"}, status_code=400)
    except (OSError, ValueError):
        logger.warning("Không vẽ được chart file %s", file_id, exc_info=True)
        return JSONResponse({"detail": "bad_chart"}, status_code=400)


@router.get("/files/{file_id}/bounds")
def bounds(file_id: int):
    record, path = _record(file_id)
    if record is None or path is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    try:
        columns = number_bounds(path, parse_schema(record))
    except (OSError, ValueError):
        columns = {}
    return {"show_colors": show_colors(file_id), "columns": columns}


@router.put("/files/{file_id}/colors")
async def colors(file_id: int, request: Request):
    if get_file(file_id) is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    enabled = bool(body.get("show")) if isinstance(body, dict) else False
    set_show_colors(file_id, enabled)
    return {"show_colors": enabled}


@router.get("/charts")
def charts(file_id: int):
    if get_file(file_id) is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return list_charts(file_id)


@router.post("/charts")
async def create_chart(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "bad_chart"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"detail": "bad_chart"}, status_code=400)
    try:
        file_id = int(body.get("file_id"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "bad_chart"}, status_code=400)
    if get_file(file_id) is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    config = body.get("config") if isinstance(body.get("config"), dict) else {}
    chart_id = save_chart(file_id, str(body.get("name") or ""), config)
    return {"id": chart_id}


@router.delete("/charts/{chart_id}")
def remove_chart(chart_id: int):
    if not delete_chart(chart_id):
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return JSONResponse({"ok": True})


@router.get("/files/{file_id}/profile")
def profile(file_id: int):
    record, path = _record(file_id)
    if record is None or path is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    try:
        columns = column_profile(file_id, path, parse_schema(record))
    except (OSError, ValueError):
        logger.warning("Không lập được profile file %s", file_id, exc_info=True)
        return JSONResponse({"detail": "bad_profile"}, status_code=400)
    return {"columns": columns}


@router.post("/files/{file_id}/pivot")
async def pivot(file_id: int, request: Request):
    record, path = _record(file_id)
    if record is None or path is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "bad_pivot"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"detail": "bad_pivot"}, status_code=400)
    try:
        table = pivot_table(path, parse_schema(record), body)
    except AnalysisError:
        return JSONResponse({"detail": "bad_pivot"}, status_code=400)
    except (OSError, ValueError):
        logger.warning("Không chạy được pivot file %s", file_id, exc_info=True)
        return JSONResponse({"detail": "bad_pivot"}, status_code=400)
    fmt = str(body.get("format") or "")
    if fmt in {"csv", "xlsx"}:
        return _pivot_file(table, fmt)
    return table


@router.get("/pivots")
def pivots(file_id: int):
    if get_file(file_id) is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return list_pivots(file_id)


@router.post("/pivots")
async def create_pivot(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "bad_pivot"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"detail": "bad_pivot"}, status_code=400)
    try:
        file_id = int(body.get("file_id"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "bad_pivot"}, status_code=400)
    if get_file(file_id) is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    config = body.get("config") if isinstance(body.get("config"), dict) else {}
    return {"id": save_pivot(file_id, str(body.get("name") or ""), config)}


@router.delete("/pivots/{pivot_id}")
def remove_pivot(pivot_id: int):
    if not delete_pivot(pivot_id):
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return JSONResponse({"ok": True})


def _pivot_file(table: dict, fmt: str):
    columns = [str(name) for name in table.get("columns") or []]
    rows = table.get("rows") or []
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote('pivot.' + fmt)}"}
    if fmt == "csv":
        return StreamingResponse(iter_csv(columns, iter(rows)), media_type="text/csv; charset=utf-8", headers=headers)
    dest = STAGING_DIR / f"{uuid4().hex}.xlsx"
    try:
        write_xlsx(dest, columns, iter(rows))
    except Exception:
        dest.unlink(missing_ok=True)
        return JSONResponse({"detail": "bad_excel"}, status_code=500)
    return FileResponse(
        dest,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
        background=BackgroundTask(dest.unlink, missing_ok=True),
    )
