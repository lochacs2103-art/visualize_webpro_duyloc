"""SSE tiến trình job nạp file."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.jobs import Job, format_event, get_job, wait_job

router = APIRouter()


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return job.public()


@router.get("/jobs/{job_id}/stream")
def job_stream(job_id: str):
    if get_job(job_id) is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return StreamingResponse(
        _events(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _events(job_id: str) -> Iterator[str]:
    last = ""
    while True:
        job: Job | None = get_job(job_id)
        if job is None:
            yield "event: error\ndata: missing\n\n"
            return
        payload = format_event(job)
        if payload != last:
            yield payload
            last = payload
        if job.status in {"done", "error"}:
            return
        wait_job(0.8)
