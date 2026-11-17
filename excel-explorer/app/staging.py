"""Lưu file upload tạm để xem trước dòng tiêu đề, rồi xoá sau khi nạp."""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import STAGING_DIR
from app.converter_errors import ConvertError

_STAGING_ID = re.compile(r"^[a-f0-9]{32}\.(xlsx|xls)$")
_XLS_MAGIC = b"\xd0\xcf\x11\xe0"


def extension_of(filename: str | None) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in {".xlsx", ".xls"}:
        raise ConvertError("bad_type")
    return ext


def dump_upload(upload: UploadFile, dest: Path) -> None:
    """Ghi theo khối 1MB, không giữ cả file trong RAM."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as handle:
        while chunk := upload.file.read(1024 * 1024):
            handle.write(chunk)


def assert_excel(path: Path, ext: str) -> None:
    with path.open("rb") as handle:
        signature = handle.read(8)
    valid = (ext == ".xlsx" and signature.startswith(b"PK")) or (ext == ".xls" and signature.startswith(_XLS_MAGIC))
    if not valid:
        path.unlink(missing_ok=True)
        raise ConvertError("bad_excel")


def stage_upload(upload: UploadFile) -> str:
    ext = extension_of(upload.filename)
    staging_id = f"{uuid4().hex}{ext}"
    dest = STAGING_DIR / staging_id
    try:
        dump_upload(upload, dest)
        assert_excel(dest, ext)
    except ConvertError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise ConvertError("bad_excel") from exc
    original = Path(upload.filename or f"upload{ext}").name
    dest.with_suffix(".json").write_text(
        json.dumps({"original_name": original}, ensure_ascii=False),
        encoding="utf-8",
    )
    return staging_id


def load_staging(staging_id: str) -> tuple[Path, str]:
    if not _STAGING_ID.fullmatch(staging_id or ""):
        raise ConvertError("staging_missing")
    path = (STAGING_DIR / staging_id).resolve()
    try:
        path.relative_to(STAGING_DIR.resolve())
    except ValueError as exc:
        raise ConvertError("staging_missing") from exc
    meta_path = path.with_suffix(".json")
    if not path.is_file() or not meta_path.is_file():
        raise ConvertError("staging_missing")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    original = Path(str(meta.get("original_name") or path.name)).name
    return path, original


def clear_staging(staging_id: str) -> None:
    if not _STAGING_ID.fullmatch(staging_id or ""):
        return
    path = STAGING_DIR / staging_id
    path.unlink(missing_ok=True)
    path.with_suffix(".json").unlink(missing_ok=True)
