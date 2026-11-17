"""Smoke test Phase 1. Chạy tay: python scripts/smoke_phase1.py"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime

import uvicorn
from openpyxl import Workbook

from app.config import APP_DIR, DATA_DIR, HOST, PORT
from app.main import app

SAMPLE = APP_DIR / "samples"
XLSX = SAMPLE / "nhan_su.xlsx"
BASE = f"http://{HOST}:{PORT}"


def build_workbook() -> None:
    SAMPLE.mkdir(exist_ok=True)
    book = Workbook()
    people = book.active
    people.title = "Nhân sự"
    people.append(["Báo cáo nhân sự"])
    people.append(["Nội bộ"])
    people.append(["Họ tên", "Ngày sinh", "Lương"])
    for index in range(1, 251):
        people.append([f"Nguyễn Văn {index}", datetime(1990, 1, min(index, 28)), 1000 + index])
    notes = book.create_sheet("Ghi chú")
    notes.append(["Ghi chú nội bộ"])
    notes.append(["Phụ lục"])
    notes.append(["Mã", "Nội dung"])
    notes.append(["A1", "Tiếng Việt có dấu"])
    book.save(XLSX)


def request(method: str, path: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, str]:
    req = urllib.request.Request(BASE + path, data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def poll_job(html: str) -> dict:
    job_id = html.split('data-job="', 1)[1].split('"', 1)[0]
    deadline = time.time() + 60
    while time.time() < deadline:
        status, body = request("GET", f"/jobs/{job_id}")
        assert status == 200, body
        payload = json.loads(body)
        if payload["status"] in {"done", "error"}:
            assert payload["status"] == "done", payload
            return payload
        time.sleep(0.2)
    raise AssertionError("job timeout")


def post_form(path: str, fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[int, str]:
    boundary = uuid.uuid4().hex
    body = bytearray()
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
    for key, (filename, content, content_type) in files.items():
        body.extend(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n".encode()
        )
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return request(
        "POST",
        path,
        bytes(body),
        {"Content-Type": f"multipart/form-data; boundary={boundary}", "HX-Request": "true"},
    )


def wait_until_up() -> None:
    for _ in range(50):
        try:
            status, _ = request("GET", "/health")
            if status == 200:
                return
        except Exception:
            time.sleep(0.2)
        else:
            time.sleep(0.2)
    raise RuntimeError("Server không lên cổng 8000")


def main() -> None:
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    build_workbook()
    threading.Thread(target=lambda: uvicorn.run(app, host=HOST, port=PORT, log_level="warning"), daemon=True).start()
    wait_until_up()

    status, health_text = request("GET", "/health")
    health = json.loads(health_text)
    assert status == 200, health_text
    assert health["engines"]["duckdb"] == "ok"
    assert health["engines"]["polars"] == "ok"
    status, home = request("GET", "/")
    assert status == 200, home
    assert "Excel Explorer" in home

    preview_status, preview = post_form(
        "/upload/preview",
        {},
        {"file": ("nhan_su.xlsx", XLSX.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert preview_status == 200, preview
    assert "Họ tên" in preview
    assert 'value="3"' in preview
    assert "checked" in preview
    staging = preview.split('name="staging_id" value="', 1)[1].split('"', 1)[0]

    commit_status, committed = post_form("/upload/commit", {"staging_id": staging, "header_row": "3"}, {})
    assert commit_status == 200, committed
    assert 'data-job="' in committed, committed
    poll_job(committed)

    _, listing_text = request("GET", "/files")
    listing = json.loads(listing_text)
    names = [item["name"] for group in listing for item in group["files"]]
    print("FILES", names)
    assert "nhan_su.xlsx" in names
    assert sum(1 for name in names if name.startswith("nhan_su")) == 1

    people = next(item for group in listing for item in group["files"] if item["row_count"] == 250)
    assert people["row_count"] == 250
    assert people["col_count"] == 3
    status, page = request("GET", f"/files/{people['id']}")
    assert status == 200, page
    assert "sheetView" in page
    _, page2 = request("GET", f"/files/{people['id']}/rows?offset=200&limit=50")
    assert "Nguyễn Văn 250" in page2
    assert "Nguyễn Văn 1" not in page2
    _, rows_text = request("GET", f"/files/{people['id']}/rows?offset=0&limit=2")
    rows = json.loads(rows_text)
    print("ROW0", rows["rows"][0])
    _, hover_text = request("GET", f"/files/{people['id']}/preview")
    hover = json.loads(hover_text)
    assert len(hover["rows"]) == 5
    status, _missing = request("GET", "/files/99999")
    assert status == 404

    bad_status, bad = post_form("/upload", {"header_row": "1"}, {"file": ("note.txt", b"hello", "text/plain")})
    assert bad_status == 200
    assert "xlsx" in bad.lower() or "bad_type" in bad

    again_status, again = post_form(
        "/upload",
        {"header_row": "3"},
        {"file": ("nhan_su.xlsx", XLSX.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert again_status == 200, again
    poll_job(again)
    _, listing2_text = request("GET", "/files")
    names2 = [item["name"] for group in json.loads(listing2_text) for item in group["files"]]
    print("FILES2", names2)
    assert sum(1 for name in names2 if name.startswith("nhan_su")) == 1, names2

    csvs = list((DATA_DIR / "csv").rglob("*.csv"))
    print("CSVS", [path.name for path in csvs])
    sample = next(path for path in csvs if path.name.startswith("nhan_su__") and "Nhân" in path.name)
    raw = sample.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    assert "Họ tên" in text
    assert "Nguyễn Văn 1" in text
    print("OK")


if __name__ == "__main__":
    main()
