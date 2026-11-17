"""Mở Excel Explorer trên localhost và trình duyệt."""

from __future__ import annotations

import logging
import os
import threading
import time
import webbrowser

import uvicorn

from app.config import HOST, PORT, DATA_DIR, setup_logging
from app.main import app


def _open_browser() -> None:
    time.sleep(1.5)
    webbrowser.open(f"http://{HOST}:{PORT}")


def main() -> None:
    setup_logging()
    logging.getLogger("excel_explorer").info("Data folder: %s", DATA_DIR)
    print(f"Data folder: {DATA_DIR}")
    print(f"Open http://{HOST}:{PORT}")
    if os.environ.get("EXCEL_EXPLORER_NO_BROWSER") != "1":
        threading.Thread(target=_open_browser, daemon=True).start()
    # Truyền app object, không truyền chuỗi import: bản PyInstaller không cần reload.
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
