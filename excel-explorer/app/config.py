"""Đường dẫn runtime và bundle.

Khi đóng gói PyInstaller, template/static nằm trong _MEIPASS.
File người dùng (data/, logs/, app.db) luôn nằm cạnh file exe.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000
PAGE_SIZE = 200
PEEK_ROWS = 10
HOVER_ROWS = 5
MAX_HEADER_ROW = 100


def is_frozen() -> bool:
    """True khi process đang chạy từ bản PyInstaller."""
    return getattr(sys, "frozen", False)


def get_app_dir() -> Path:
    """Thư mục dữ liệu. Bản đóng gói mặc định nằm cạnh exe. run.bat có thể trỏ sang thư mục project."""
    override = os.environ.get("EXCEL_EXPLORER_HOME", "").strip().strip('"')
    if override:
        return Path(override)
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def get_bundle_dir() -> Path:
    """Thư mục templates/static. Nằm trong _MEIPASS khi đã đóng gói."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


APP_DIR = get_app_dir()
BUNDLE_DIR = get_bundle_dir()
DATA_DIR = APP_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
CSV_DIR = DATA_DIR / "csv"
PARQUET_DIR = DATA_DIR / "parquet"
INBOX_DIR = DATA_DIR / "inbox"
STAGING_DIR = DATA_DIR / "staging"
RAW_UPLOADS_DIR = DATA_DIR / "raw-uploads"
MAPPED_DIR = CSV_DIR / "raw-mapped"
LOG_DIR = APP_DIR / "logs"
DB_PATH = DATA_DIR / "app.db"
TEMPLATES_DIR = BUNDLE_DIR / "templates"
STATIC_DIR = BUNDLE_DIR / "static"


def ensure_dirs() -> None:
    """Tạo thư mục dữ liệu cạnh app. Gọi lại nhiều lần cũng an toàn."""
    for path in (DATA_DIR, RAW_DIR, CSV_DIR, PARQUET_DIR, INBOX_DIR, STAGING_DIR, RAW_UPLOADS_DIR, MAPPED_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def to_rel(path: Path) -> str:
    """Đường dẫn tương đối so với thư mục app, dùng dấu / để mang máy khác vẫn đúng."""
    return path.resolve().relative_to(APP_DIR.resolve()).as_posix()


def from_rel(rel: str) -> Path:
    """Đổi đường dẫn đã lưu thành path thật. Từ chối path tuyệt đối và `..`."""
    if not rel:
        raise ValueError("Đường dẫn rỗng")
    parts = Path(rel).parts
    if Path(rel).is_absolute() or ".." in parts:
        raise ValueError("Đường dẫn không an toàn")
    full = (APP_DIR / rel).resolve()
    full.relative_to(APP_DIR.resolve())
    return full


def configure_stdio() -> None:
    """Windows console mặc định không phải UTF-8. Ép stdout để log tiếng Việt không vỡ."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            continue


def setup_logging() -> None:
    """Ghi log ra logs/app.log và console."""
    ensure_dirs()
    configure_stdio()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )


ensure_dirs()
