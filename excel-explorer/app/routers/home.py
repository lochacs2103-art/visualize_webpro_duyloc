"""API trang chủ: thống kê và file gần đây."""

from __future__ import annotations

from fastapi import APIRouter

from app.homeboard import recent_files, stats

router = APIRouter()


@router.get("/stats")
def home_stats() -> dict:
    return stats()


@router.get("/recent-files")
def home_recent() -> list[dict]:
    return recent_files()
