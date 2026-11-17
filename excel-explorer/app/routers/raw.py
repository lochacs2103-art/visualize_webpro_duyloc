"""File raw: giữ Excel, xem trước, nạp vào thư viện hoặc xóa."""

from __future__ import annotations

import logging
from threading import Thread

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.config import from_rel
from app.converter_errors import ConvertError
from app.ingest import register_excel
from app.jobs import create_job, fail_job, finish_job, update_job
from app.rawfiles import delete_raw, get_raw, list_raw, peek_sheet, save_upload
from app.templating import render, templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/raw")
def raw_page(request: Request):
    return render(request, "raw.html", {"raw_files": list_raw()})


@router.get("/raw/list")
def raw_list() -> list[dict]:
    return list_raw()


@router.post("/raw/upload")
async def raw_upload(files: list[UploadFile] = File(...)):
    saved = 0
    for item in files:
        payload = await item.read()
        if not payload:
            continue
        try:
            save_upload(item.filename or "file.xlsx", payload)
            saved += 1
        except ConvertError:
            logger.warning("Bỏ qua file raw không đọc được: %s", item.filename)
    if saved == 0:
        return JSONResponse({"detail": "bad_type"}, status_code=400)
    return Response(status_code=204, headers={"HX-Redirect": "/raw"})


@router.get("/raw/{raw_id}/preview", response_class=HTMLResponse)
def raw_preview(request: Request, raw_id: int, sheet: str = "", header: int = 1):
    record = get_raw(raw_id)
    if record is None:
        return render(request, "error.html", {"message_key": "not_found"}, status_code=404)
    chosen = sheet or (record["sheets"][0] if record["sheets"] else "")
    try:
        rows = peek_sheet(from_rel(record["path"]), chosen, 10)
    except (ConvertError, OSError, ValueError):
        return render(request, "partials/flash.html", {"message_key": "bad_excel"})
    return render(
        request,
        "partials/raw_preview.html",
        {"raw": record, "sheet": chosen, "rows": rows, "header": header},
    )


@router.post("/raw/{raw_id}/convert")
def raw_convert(raw_id: int, header_row: int = Form(1)):
    record = get_raw(raw_id)
    if record is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    path = from_rel(record["path"])
    job = create_job(record["name"])
    Thread(target=_convert, args=(job.id, path, record["name"], header_row), daemon=True).start()
    html = templates.env.get_template("partials/job.html").render({"job_id": job.id, "filename": record["name"]})
    return HTMLResponse(html)


@router.delete("/raw/{raw_id}")
def raw_delete(raw_id: int):
    delete_raw(raw_id)
    return Response(status_code=204, headers={"HX-Redirect": "/raw"})


def _convert(job_id: str, path, name: str, header_row: int) -> None:
    try:
        records = register_excel(
            path,
            name,
            header_row,
            lambda pct, detail: update_job(job_id, pct, "job_sheet", detail),
        )
        best = max(records, key=lambda item: int(item.get("row_count") or 0))
        finish_job(job_id, int(best["id"]))
    except ConvertError as exc:
        fail_job(job_id, exc.code)
    except Exception:
        logger.exception("Convert raw thất bại")
        fail_job(job_id, "bad_excel")
