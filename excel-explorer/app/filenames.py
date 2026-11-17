"""Tên file an toàn trên Windows và chống ghi đè trong cùng một ngày."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.converter_errors import ConvertError

_MONTH = re.compile(r"(?:thang|month|t)[_\s-]?(\d{1,2})", re.IGNORECASE)

_INVALID = '<>:"/\\|?*'
_RESERVED = {"CON", "PRN", "AUX", "NUL"}
_RESERVED.update({f"COM{i}" for i in range(1, 10)})
_RESERVED.update({f"LPT{i}" for i in range(1, 10)})


def short_file_label(name: str) -> str:
    """T10, T11 nếu tên có tháng. Không thì giữ đoạn đầu, tên đầy đủ để ở tooltip."""
    stem = Path(str(name or "").replace("\\", "/")).stem
    found = list(_MONTH.finditer(stem))
    if found:
        return f"T{int(found[-1].group(1))}"
    if len(stem) > 14:
        return stem[:14] + "…"
    return stem or "file"


def safe_stem(value: str, fallback: str = "file") -> str:
    """Bỏ ký tự cấm của Windows, giữ chữ tiếng Việt."""
    cleaned = []
    for char in value.strip():
        if char in _INVALID or ord(char) < 32:
            cleaned.append("_")
        else:
            cleaned.append(char)
    name = "".join(cleaned).strip(" .")
    if not name:
        name = fallback
    if name.upper() in _RESERVED:
        name = f"_{name}"
    return name[:80]


def unique_path(folder: Path, stem: str, ext: str) -> Path:
    """Nếu `stem.ext` đã có, thêm `_HHMMSS` đúng quy ước của spec."""
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / f"{stem}{ext}"
    if not candidate.exists():
        return candidate
    stamp = datetime.now().strftime("%H%M%S")
    candidate = folder / f"{stem}_{stamp}{ext}"
    if not candidate.exists():
        return candidate
    for number in range(2, 1000):
        candidate = folder / f"{stem}_{stamp}_{number}{ext}"
        if not candidate.exists():
            return candidate
    raise ConvertError("bad_excel")
