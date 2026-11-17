"""Upload Excel: nạp thẳng, hoặc xem 10 dòng rồi chọn dòng tiêu đề."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from app.config import STAGING_DIR
from app.converter_errors import ConvertError
from app.excel_preview import peek_excel
from app.ingest import register_excel
from app.jobs import create_job, fail_job, finish_job, update_job
from app.present import library_context
from app.staging import assert_excel, clear_staging, dump_upload, extension_of, load_staging, stage_upload
from app.templating import render

logger = logging.getLogger(__name__)
router = APIRouter()


def _library(request: Request, message_key: str, added: list | None = None, *, ok: bool = False):
    htmx = bool(request.headers.get("HX-Request"))
    context = library_context(
        message_key=message_key,
        added=added,
        oob_clear_preview=ok,
        stage_error=htmx and not ok,
    )
    if htmx:
        response = render(request, "partials/library.html", context)
        if ok and added:
            response.headers["HX-Redirect"] = f"/files/{added[0]['id']}"
        return response
    if ok and added:
        return RedirectResponse(f"/files/{added[0]['id']}", status_code=303)
    if ok:
        return RedirectResponse("/", status_code=303)
    return render(request, "explorer.html", context, status_code=400)


@router.post("/upload/preview")
def upload_preview(request: Request, file: UploadFile = File(...)):
    try:
        staging_id = stage_upload(file)
        path, original = load_staging(staging_id)
        preview = peek_excel(path)
    except ConvertError as exc:
        return render(request, "partials/preview_error.html", {"message_key": exc.code})
    except Exception:
        logger.exception("Xem trước Excel thất bại")
        return render(request, "partials/preview_error.html", {"message_key": "bad_excel"})
    return render(
        request,
        "partials/header_preview.html",
        {"preview": preview, "staging_id": staging_id, "filename": original},
    )


@router.post("/upload/commit")
def upload_commit(request: Request, staging_id: str = Form(...), header_row: int = Form(...)):
    try:
        path, original = load_staging(staging_id)
    except ConvertError as exc:
        return _stage_error(request, exc.code)
    except Exception:
        logger.exception("Không thấy bản xem trước")
        return _stage_error(request, "staging_missing")
    job_id = _start_job(path, original, header_row, staging_id=staging_id)
    return _job_page(request, job_id, original)


@router.post("/upload")
def upload(request: Request, file: UploadFile = File(...), header_row: int = Form(1)):
    """Lưu file rồi convert trong job nền. Tiến trình đi qua SSE."""
    ext = extension_of(file.filename)
    temp = STAGING_DIR / f"{uuid4().hex}{ext}"
    try:
        dump_upload(file, temp)
        assert_excel(temp, ext)
    except ConvertError as exc:
        temp.unlink(missing_ok=True)
        return _stage_error(request, exc.code)
    except Exception:
        temp.unlink(missing_ok=True)
        logger.exception("Upload thất bại")
        return _stage_error(request, "bad_excel")
    original = file.filename or f"upload{ext}"
    job_id = _start_job(temp, original, header_row, unlink=temp)
    return _job_page(request, job_id, original)


def _job_page(request: Request, job_id: str, filename: str):
    if request.headers.get("HX-Request"):
        return render(request, "partials/job.html", {"job_id": job_id, "filename": filename})
    return render(request, "explorer.html", library_context())


def _stage_error(request: Request, code: str):
    if request.headers.get("HX-Request"):
        return render(request, "partials/preview_error.html", {"message_key": code})
    return _library(request, code)


def _start_job(path: Path, original: str, header_row: int, unlink: Path | None = None, staging_id: str | None = None) -> str:
    job = create_job(original)

    def run() -> None:
        try:
            update_job(job.id, 5, "job_copy", original)

            def report(percent: int, detail: str) -> None:
                update_job(job.id, percent, "job_sheet", detail)

            added = register_excel(path, original, header_row, on_progress=report)
            target = max(added, key=lambda item: int(item.get("row_count") or 0))
            if staging_id:
                clear_staging(staging_id)
            finish_job(job.id, int(target["id"]))
        except ConvertError as exc:
            fail_job(job.id, exc.code)
        except Exception:
            logger.exception("Job nạp thất bại: %s", original)
            fail_job(job.id, "bad_excel")
        finally:
            if unlink is not None:
                unlink.unlink(missing_ok=True)

    threading.Thread(target=run, daemon=True, name=f"job-{job.id[:8]}").start()
    return job.id
