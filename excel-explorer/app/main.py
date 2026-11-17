"""FastAPI app. uvicorn nhận object này để chạy được cả lúc đóng gói."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import STATIC_DIR, setup_logging
from app.database import init_db
from app.compat import log_status
from app.routers import export, files, home, jobs, mappings, raw, studio, upload, visualize

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    init_db()
    log_status()
    logger.info("Excel Explorer %s", __version__)
    yield


app = FastAPI(title="Excel Explorer", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(files.router)
app.include_router(visualize.router)
app.include_router(home.router)
app.include_router(raw.router)
app.include_router(mappings.router)
app.include_router(studio.router)
app.include_router(export.router)
app.include_router(jobs.router)
app.include_router(upload.router)


@app.get("/health")
def health() -> dict[str, object]:
    engines: dict[str, str] = {}
    for name in ("duckdb", "polars", "openpyxl"):
        try:
            __import__(name)
            engines[name] = "ok"
        except Exception as exc:
            engines[name] = str(exc)
    return {"status": "ok", "version": __version__, "engines": engines}
