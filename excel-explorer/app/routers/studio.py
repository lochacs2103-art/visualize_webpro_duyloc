"""Trang tổng hợp: lọc, nhóm, cộng, công thức."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.database import get_file, workbook_name
from app.studio import StudioError, column_list, preview, save
from app.templating import render

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/studio/{file_id}")
def studio_page(request: Request, file_id: int):
    record = get_file(file_id)
    if record is None:
        return render(request, "error.html", {"message_key": "not_found"}, status_code=404)
    meta = json.dumps(
        {"file_id": file_id, "name": workbook_name(record), "columns": column_list(record)},
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    return render(request, "studio.html", {"file": record, "name": workbook_name(record), "meta": meta})


@router.post("/studio/preview")
async def studio_preview(request: Request):
    body = await request.json()
    try:
        file_id = int(body.get("file_id") or 0)
    except (TypeError, ValueError):
        return JSONResponse({"error": "bad_config"}, status_code=400)
    try:
        return preview(file_id, body)
    except StudioError as exc:
        return JSONResponse({"columns": [], "rows": [], "error": exc.code})
    except Exception:
        logger.exception("Xem trước studio thất bại")
        return JSONResponse({"columns": [], "rows": [], "error": "bad_config"})


@router.post("/studio/save")
async def studio_save(request: Request):
    body = await request.json()
    try:
        file_id = int(body.get("file_id") or 0)
    except (TypeError, ValueError):
        return JSONResponse({"error": "bad_config"}, status_code=400)
    try:
        return save(file_id, body)
    except StudioError as exc:
        return JSONResponse({"error": exc.code}, status_code=400)
    except Exception:
        logger.exception("Lưu studio thất bại")
        return JSONResponse({"error": "bad_config"}, status_code=400)
