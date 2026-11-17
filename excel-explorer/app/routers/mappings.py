"""Project gộp cột nhiều file raw thành một CSV."""

from __future__ import annotations

import json
import logging
from threading import Thread

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.converter_errors import ConvertError
from app.database import get_file
from app.jobs import create_job, fail_job, finish_job, update_job
from app.mapping_engine import preview_project, run_project, source_headers, suggest_mapping, sum_column
from app.mapping_store import (
    add_file,
    clone_project,
    create_project,
    delete_column,
    delete_map,
    delete_project,
    ensure_column,
    get_project,
    link_views,
    list_projects,
    list_runs,
    remove_file,
    save_links,
    update_column,
    update_map_transform,
    update_project,
    upsert_map,
)
from app.rawfiles import list_raw
from app.templating import render, templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/mappings")
def mapping_page(request: Request):
    return render(request, "mappings.html", {"projects": list_projects()})


@router.post("/mappings")
def mapping_create(name: str = Form(...), description: str = Form("")):
    project_id = create_project(name, description)
    return Response(status_code=204, headers={"HX-Redirect": f"/mappings/{project_id}"})


@router.get("/mappings/{project_id}")
def mapping_detail(request: Request, project_id: int):
    project = _view(project_id)
    if project is None:
        return render(request, "error.html", {"message_key": "not_found"}, status_code=404)
    state = json.dumps({"links": link_views(project)}, ensure_ascii=False).replace("<", "\\u003c")
    return render(
        request,
        "mapping_edit.html",
        {"project": project, "raw_files": list_raw(), "map_state": state},
    )


@router.put("/mappings/{project_id}")
def mapping_update(project_id: int, name: str = Form(...), description: str = Form("")):
    if get_project(project_id) is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    update_project(project_id, name, description)
    return Response(status_code=204, headers={"HX-Redirect": f"/mappings/{project_id}"})


@router.delete("/mappings/{project_id}")
def mapping_delete(project_id: int):
    delete_project(project_id)
    return Response(status_code=204, headers={"HX-Redirect": "/mappings"})


@router.post("/mappings/{project_id}/clone")
def mapping_clone(project_id: int):
    new_id = clone_project(project_id)
    if new_id is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return Response(status_code=204, headers={"HX-Redirect": f"/mappings/{new_id}"})


@router.post("/mappings/{project_id}/files")
def mapping_add_file(
    project_id: int,
    raw_file_id: int = Form(...),
    sheet_name: str = Form(...),
    header_row: int = Form(1),
):
    if get_project(project_id) is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    add_file(project_id, raw_file_id, sheet_name, max(1, min(100, header_row)))
    return Response(status_code=204, headers={"HX-Redirect": f"/mappings/{project_id}"})


@router.delete("/mappings/{project_id}/files/{mapping_file_id}")
def mapping_remove_file(project_id: int, mapping_file_id: int):
    remove_file(project_id, mapping_file_id)
    return Response(status_code=204, headers={"HX-Redirect": f"/mappings/{project_id}"})


@router.post("/mappings/{project_id}/columns")
async def mapping_add_column(project_id: int, request: Request):
    if get_project(project_id) is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    if "application/json" in request.headers.get("content-type", ""):
        body = await request.json()
        column_name = str(body.get("column_name") or "")
        data_type = str(body.get("data_type") or "")
        as_json = True
    else:
        form = await request.form()
        column_name = str(form.get("column_name") or "")
        data_type = str(form.get("data_type") or "text")
        as_json = False
    if not column_name.strip():
        return JSONResponse({"detail": "bad_column"}, status_code=400)
    if data_type not in {"text", "number", "date", "boolean"}:
        data_type = _guess_type(column_name)
    column_id, kind = ensure_column(project_id, column_name, data_type)
    if as_json:
        return JSONResponse({"id": column_id, "column_name": column_name.strip(), "data_type": kind})
    return Response(status_code=204, headers={"HX-Redirect": f"/mappings/{project_id}"})


@router.put("/mappings/{project_id}/columns/{column_id}")
def mapping_edit_column(
    project_id: int,
    column_id: int,
    column_name: str = Form(...),
    data_type: str = Form("text"),
):
    update_column(project_id, column_id, column_name, data_type)
    return Response(status_code=204, headers={"HX-Redirect": f"/mappings/{project_id}"})


@router.delete("/mappings/{project_id}/columns/{column_id}")
def mapping_delete_column(project_id: int, column_id: int):
    delete_column(project_id, column_id)
    return Response(status_code=204, headers={"HX-Redirect": f"/mappings/{project_id}"})


@router.post("/mappings/{project_id}/links")
async def mapping_save_links(project_id: int, request: Request):
    form = await request.form()
    save_links(project_id, _links_from_form(form))
    return Response(status_code=204, headers={"HX-Redirect": f"/mappings/{project_id}"})


@router.post("/mappings/{project_id}/auto-suggest")
def mapping_suggest(project_id: int):
    project = _view(project_id)
    if project is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    links = []
    for item in project["files"]:
        suggested = suggest_mapping(item["headers"], [column["column_name"] for column in project["columns"]])
        by_name = {column["column_name"]: int(column["id"]) for column in project["columns"]}
        kinds = {column["column_name"]: column["data_type"] for column in project["columns"]}
        for target_name, source_name in suggested.items():
            links.append(
                {
                    "mapping_file_id": int(item["id"]),
                    "target_column_id": by_name[target_name],
                    "source": source_name,
                    "transform": _suggest_transform(kinds.get(target_name, "text")),
                }
            )
    save_links(project_id, links)
    return Response(status_code=204, headers={"HX-Redirect": f"/mappings/{project_id}"})


@router.post("/mappings/{project_id}/files/{mapping_file_id}/map")
async def mapping_set_map(project_id: int, mapping_file_id: int, request: Request):
    body = await request.json()
    transform = body.get("transform_json") if isinstance(body.get("transform_json"), dict) else {}
    try:
        target_id = int(body.get("target_col_id") or 0)
    except (TypeError, ValueError):
        return JSONResponse({"detail": "bad_map"}, status_code=400)
    saved = upsert_map(project_id, mapping_file_id, target_id, str(body.get("source_col") or ""), transform)
    if saved is None:
        return JSONResponse({"detail": "bad_map"}, status_code=400)
    return JSONResponse(saved)


@router.delete("/mappings/{project_id}/files/{mapping_file_id}/map/{map_id}")
def mapping_clear_map(project_id: int, mapping_file_id: int, map_id: int):
    if not delete_map(project_id, mapping_file_id, map_id):
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return Response(status_code=204)


@router.put("/mappings/{project_id}/map/{map_id}/transform")
async def mapping_transform(project_id: int, map_id: int, request: Request):
    body = await request.json()
    transform = body.get("transform_json") if isinstance(body.get("transform_json"), dict) else {}
    saved = update_map_transform(project_id, map_id, transform)
    if saved is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return JSONResponse(saved)


@router.post("/mappings/{project_id}/preview", response_class=HTMLResponse)
def mapping_preview(project_id: int):
    project = get_project(project_id)
    if project is None:
        return HTMLResponse('<p class="text-sm text-red-700" data-i18n="not_found">Không tìm thấy.</p>')
    if not project["files"]:
        return HTMLResponse('<p class="text-sm text-red-700" data-i18n="map_no_files">Chưa có file nguồn.</p>')
    if not project["columns"]:
        return HTMLResponse('<p class="text-sm text-red-700" data-i18n="map_no_cols">Thêm ít nhất một cột chuẩn.</p>')
    try:
        payload = preview_project(project_id)
    except ConvertError as exc:
        return HTMLResponse(f'<p class="text-sm text-red-700" data-i18n="{exc.code}">{exc.code}</p>')
    html = templates.env.get_template("partials/map_preview.html").render(
        {
            "preview": payload,
            "types": {column["column_name"]: column["data_type"] for column in project["columns"]},
            "linked": len(project["links"]),
        }
    )
    return HTMLResponse(html)


@router.post("/mappings/{project_id}/run", response_class=HTMLResponse)
def mapping_run(project_id: int, mode: str = Form("")):
    project = get_project(project_id)
    if project is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    if not project["files"]:
        return HTMLResponse('<p class="text-sm text-red-700" data-i18n="map_no_files">Chưa có file nguồn.</p>')
    if not project["columns"]:
        return HTMLResponse('<p class="text-sm text-red-700" data-i18n="map_no_cols">Thêm ít nhất một cột chuẩn.</p>')
    if project.get("last_output") and mode not in {"overwrite", "copy"}:
        html = templates.env.get_template("partials/map_confirm.html").render({"project_id": project_id})
        return HTMLResponse(html)
    job = create_job(project["name"])
    Thread(target=_run, args=(job.id, project_id, mode or "copy"), daemon=True).start()
    html = templates.env.get_template("partials/job.html").render(
        {"job_id": job.id, "filename": project["name"], "stay": True}
    )
    return HTMLResponse(html)


@router.post("/mappings/{project_id}/sum", response_class=HTMLResponse)
def mapping_sum(project_id: int, column_name: str = Form("")):
    project = get_project(project_id)
    if project is None:
        return HTMLResponse('<p class="text-sm text-red-700" data-i18n="not_found">Không tìm thấy.</p>')
    if not any(column["data_type"] == "number" and column["column_name"] == column_name for column in project["columns"]):
        return HTMLResponse('<p class="text-sm text-red-700" data-i18n="map_sum_none">Chưa có cột số để cộng.</p>')
    try:
        payload = sum_column(project_id, column_name)
    except ConvertError as exc:
        return HTMLResponse(f'<p class="text-sm text-red-700" data-i18n="{exc.code}">{exc.code}</p>')
    html = templates.env.get_template("partials/map_sum.html").render(payload)
    return HTMLResponse(html)


@router.post("/mappings/{project_id}/continue")
def mapping_continue(project_id: int):
    project = get_project(project_id)
    if project is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    if not project["files"]:
        return HTMLResponse('<p class="text-sm text-red-700" data-i18n="map_no_files">Chưa có file nguồn.</p>')
    if not project["columns"]:
        return HTMLResponse('<p class="text-sm text-red-700" data-i18n="map_no_cols">Thêm ít nhất một cột chuẩn.</p>')
    last = project.get("last_output")
    if last:
        record = get_file(int(last["file_id"]))
        if record:
            return JSONResponse({"file_id": int(record["id"])})
    job = create_job(project["name"])
    Thread(target=_run, args=(job.id, project_id, "copy"), daemon=True).start()
    html = templates.env.get_template("partials/job.html").render(
        {"job_id": job.id, "filename": project["name"], "studio": True}
    )
    return HTMLResponse(html)


@router.get("/mappings/{project_id}/runs")
def mapping_runs(project_id: int) -> list[dict]:
    return list_runs(project_id)


def _view(project_id: int) -> dict | None:
    project = get_project(project_id)
    if project is None:
        return None
    chosen = {}
    for link in project["links"]:
        chosen[(int(link["mapping_file_id"]), int(link["target_column_id"]))] = link["source_column_name"]
    for item in project["files"]:
        try:
            item["headers"] = source_headers(item)
        except (ConvertError, OSError, ValueError):
            item["headers"] = []
        item["chosen"] = {
            column_id: source
            for (file_id, column_id), source in chosen.items()
            if file_id == int(item["id"])
        }
    return project


def _guess_type(name: str) -> str:
    import unicodedata

    folded = "".join(
        char for char in unicodedata.normalize("NFD", name.lower()) if unicodedata.category(char) != "Mn"
    )
    if any(token in folded for token in ("ngay", "date", "time")):
        return "date"
    if any(token in folded for token in ("tien", "amount", "qty", "so luong", "thanh tien")):
        return "number"
    return "text"


def _suggest_transform(data_type: str) -> dict:
    base = {"trim": True}
    if data_type == "date":
        base["date_format"] = "dd/mm/yyyy"
    elif data_type == "number":
        base["number_format"] = "eu"
        base["strip_dot"] = True
        base["strip_comma"] = True
        base["strip_currency"] = True
    return base


def _links_from_form(form) -> list[dict]:
    links = []
    for key, value in form.multi_items():
        if not str(key).startswith("src-"):
            continue
        _prefix, file_id, column_id = str(key).split("-", 2)
        transform = {
            "trim": form.get(f"trim-{file_id}-{column_id}") == "1",
            "case": form.get(f"case-{file_id}-{column_id}") or "",
            "date_format": form.get(f"date-{file_id}-{column_id}") or "",
            "number_format": form.get(f"num-{file_id}-{column_id}") or "us",
            "default": form.get(f"default-{file_id}-{column_id}") or "",
        }
        links.append(
            {
                "mapping_file_id": int(file_id),
                "target_column_id": int(column_id),
                "source": str(value or ""),
                "transform": transform,
            }
        )
    return links


def _run(job_id: str, project_id: int, mode: str) -> None:
    try:
        result = run_project(
            project_id,
            mode,
            lambda pct, key: update_job(job_id, pct, key, ""),
        )
        finish_job(job_id, int(result["file_id"]), "map_done", str(result["row_count"]))
    except ConvertError as exc:
        fail_job(job_id, exc.code)
    except Exception:
        logger.exception("Chạy mapping thất bại")
        fail_job(job_id, "bad_excel")
