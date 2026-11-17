"""Job nạp file trong nền. Một user localhost, giữ trong bộ nhớ."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from uuid import uuid4


@dataclass
class Job:
    id: str
    status: str
    progress: int
    message_key: str
    detail: str
    file_id: int | None = None
    error: str | None = None

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "message_key": self.message_key,
            "detail": self.detail,
            "file_id": self.file_id,
            "error": self.error,
        }


_lock = threading.Lock()
_jobs: dict[str, Job] = {}
_wake = threading.Condition(_lock)


def create_job(detail: str = "") -> Job:
    job = Job(id=uuid4().hex, status="running", progress=0, message_key="uploading", detail=detail)
    with _wake:
        _jobs[job.id] = job
        if len(_jobs) > 40:
            old = [item_id for item_id, item in _jobs.items() if item.status != "running"]
            for item_id in old[:-20]:
                _jobs.pop(item_id, None)
        _wake.notify_all()
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def update_job(job_id: str, progress: int, message_key: str, detail: str = "") -> None:
    with _wake:
        job = _jobs.get(job_id)
        if job is None or job.status != "running":
            return
        job.progress = max(0, min(99, progress))
        job.message_key = message_key
        job.detail = detail
        _wake.notify_all()


def finish_job(job_id: str, file_id: int, message_key: str = "upload_ok", detail: str = "") -> None:
    with _wake:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.status = "done"
        job.progress = 100
        job.file_id = file_id
        job.message_key = message_key
        if detail:
            job.detail = detail
        _wake.notify_all()


def fail_job(job_id: str, code: str) -> None:
    with _wake:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.status = "error"
        job.progress = 100
        job.error = code
        job.message_key = code
        _wake.notify_all()


def wait_job(timeout: float = 1.0) -> None:
    with _wake:
        _wake.wait(timeout)


def format_event(job: Job) -> str:
    payload = json.dumps(job.public(), ensure_ascii=False)
    return f"data: {payload}\n\n"
