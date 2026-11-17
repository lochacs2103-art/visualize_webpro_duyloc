"""Dữ liệu dùng chung cho trang thư viện."""

from __future__ import annotations

from typing import Any

from app.database import list_tree
from app.homeboard import board


def library_context(
    message_key: str | None = None,
    added: list[dict[str, Any]] | None = None,
    oob_clear_preview: bool = False,
    stage_error: bool = False,
) -> dict[str, Any]:
    home = board()
    return {
        "tree": list_tree(),
        "message_key": message_key,
        "added": added or [],
        "oob_clear_preview": oob_clear_preview,
        "stage_error": stage_error,
        "stats": home["stats"],
        "recent": home["recent"],
        "common_columns": home["columns"],
        "columns_json": home["columns_json"],
    }
