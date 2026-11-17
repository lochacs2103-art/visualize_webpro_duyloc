"""Jinja2, dùng chữ ký TemplateResponse của Starlette hiện tại."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.config import TEMPLATES_DIR
from app.filenames import short_file_label

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["short_name"] = short_file_label


def render(request: Request, name: str, context: dict[str, Any] | None = None, status_code: int = 200) -> Response:
    payload = dict(context or {})
    return templates.TemplateResponse(request, name, payload, status_code=status_code)
