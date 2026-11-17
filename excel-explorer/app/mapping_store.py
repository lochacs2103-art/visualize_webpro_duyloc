"""Đọc ghi project mapping. Không chạy UNION ở đây."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.database import connect

_TYPES = {"text", "number", "date", "boolean"}


def list_projects() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.*,
              (SELECT COUNT(*) FROM mapping_files f WHERE f.project_id = p.id) AS file_count,
              (SELECT MAX(run_at) FROM mapping_outputs o WHERE o.project_id = p.id) AS last_run
            FROM mapping_projects p
            ORDER BY p.updated_at DESC, p.id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_project(project_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM mapping_projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return None
    project = dict(row)
    project["files"] = _files(project_id)
    project["columns"] = _columns(project_id)
    project["links"] = _links(project_id)
    project["last_output"] = _last_output(project_id)
    return project


def create_project(name: str, description: str = "") -> int:
    now = _now()
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO mapping_projects (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name.strip() or "Mapping", description.strip(), now, now),
        )
        return int(cursor.lastrowid)


def update_project(project_id: int, name: str, description: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE mapping_projects SET name = ?, description = ?, updated_at = ? WHERE id = ?",
            (name.strip() or "Mapping", description.strip(), _now(), project_id),
        )


def delete_project(project_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM mapping_projects WHERE id = ?", (project_id,))


def add_file(project_id: int, raw_file_id: int, sheet_name: str, header_row: int) -> int:
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO mapping_files (project_id, raw_file_id, sheet_name, header_row, is_active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(project_id, raw_file_id, sheet_name)
            DO UPDATE SET header_row = excluded.header_row, is_active = 1
            RETURNING id
            """,
            (project_id, raw_file_id, sheet_name, header_row),
        )
        row = cursor.fetchone()
    _touch(project_id)
    return int(row[0])


def remove_file(project_id: int, mapping_file_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM mapping_files WHERE id = ? AND project_id = ?",
            (mapping_file_id, project_id),
        )
    _touch(project_id)


def add_column(project_id: int, name: str, data_type: str) -> int:
    column_id, _kind = ensure_column(project_id, name, data_type)
    return column_id


def ensure_column(project_id: int, name: str, data_type: str) -> tuple[int, str]:
    """Tạo cột chuẩn. Tên đã có thì trả về cột đó, không tạo bản trùng."""
    cleaned = name.strip()
    kind = data_type if data_type in _TYPES else "text"
    with connect() as conn:
        found = conn.execute(
            "SELECT id, data_type FROM mapping_target_columns WHERE project_id = ? AND column_name = ?",
            (project_id, cleaned),
        ).fetchone()
        if found is not None:
            return int(found[0]), str(found[1])
        position = conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM mapping_target_columns WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]
        cursor = conn.execute(
            """
            INSERT INTO mapping_target_columns (project_id, column_name, data_type, position)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, cleaned, kind, int(position)),
        )
        column_id = int(cursor.lastrowid)
    _touch(project_id)
    return column_id, kind


def update_column(project_id: int, column_id: int, name: str, data_type: str) -> None:
    kind = data_type if data_type in _TYPES else "text"
    with connect() as conn:
        conn.execute(
            """
            UPDATE mapping_target_columns
            SET column_name = ?, data_type = ?
            WHERE id = ? AND project_id = ?
            """,
            (name.strip(), kind, column_id, project_id),
        )
    _touch(project_id)


def delete_column(project_id: int, column_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM mapping_target_columns WHERE id = ? AND project_id = ?",
            (column_id, project_id),
        )
    _touch(project_id)


def link_views(project: dict[str, Any]) -> list[dict[str, Any]]:
    files = {int(item["id"]): item for item in project["files"]}
    columns = {int(item["id"]): item for item in project["columns"]}
    views = []
    for link in project["links"]:
        view = _view_link(link, files, columns)
        if view:
            views.append(view)
    return views


def upsert_map(
    project_id: int,
    mapping_file_id: int,
    target_column_id: int,
    source: str,
    transform: dict[str, Any] | None,
) -> dict[str, Any] | None:
    source = source.strip()
    if not source:
        return None
    blob = json.dumps(_clean_transform(transform or {}), ensure_ascii=False)
    with connect() as conn:
        owned = conn.execute(
            "SELECT 1 FROM mapping_files WHERE id = ? AND project_id = ?",
            (mapping_file_id, project_id),
        ).fetchone()
        target = conn.execute(
            "SELECT 1 FROM mapping_target_columns WHERE id = ? AND project_id = ?",
            (target_column_id, project_id),
        ).fetchone()
        if owned is None or target is None:
            return None
        row = conn.execute(
            """
            INSERT INTO mapping_column_map
              (mapping_file_id, target_column_id, source_column_name, transform_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(mapping_file_id, target_column_id)
            DO UPDATE SET source_column_name = excluded.source_column_name,
                          transform_json = excluded.transform_json
            RETURNING id
            """,
            (mapping_file_id, target_column_id, source, blob),
        ).fetchone()
    _touch(project_id)
    return _saved_link(project_id, int(row[0]))


def delete_map(project_id: int, mapping_file_id: int, map_id: int) -> bool:
    with connect() as conn:
        cursor = conn.execute(
            """
            DELETE FROM mapping_column_map
            WHERE id = ? AND mapping_file_id = ?
              AND mapping_file_id IN (SELECT id FROM mapping_files WHERE project_id = ?)
            """,
            (map_id, mapping_file_id, project_id),
        )
        removed = cursor.rowcount > 0
    if removed:
        _touch(project_id)
    return removed


def update_map_transform(project_id: int, map_id: int, transform: dict[str, Any] | None) -> dict[str, Any] | None:
    blob = json.dumps(_clean_transform(transform or {}), ensure_ascii=False)
    with connect() as conn:
        row = conn.execute(
            """
            UPDATE mapping_column_map
            SET transform_json = ?
            WHERE id = ?
              AND mapping_file_id IN (SELECT id FROM mapping_files WHERE project_id = ?)
            RETURNING id
            """,
            (blob, map_id, project_id),
        ).fetchone()
    if row is None:
        return None
    _touch(project_id)
    return _saved_link(project_id, int(row[0]))


def save_links(project_id: int, links: list[dict[str, Any]]) -> None:
    """Mỗi phần tử: mapping_file_id, target_column_id, source, transform."""
    file_ids = [int(item["mapping_file_id"]) for item in links]
    with connect() as conn:
        owned = {
            int(row[0])
            for row in conn.execute("SELECT id FROM mapping_files WHERE project_id = ?", (project_id,))
        }
        targets = {
            int(row[0])
            for row in conn.execute("SELECT id FROM mapping_target_columns WHERE project_id = ?", (project_id,))
        }
        for file_id in set(file_ids):
            if file_id in owned:
                conn.execute("DELETE FROM mapping_column_map WHERE mapping_file_id = ?", (file_id,))
        for item in links:
            file_id = int(item["mapping_file_id"])
            target_id = int(item["target_column_id"])
            source = str(item.get("source") or "").strip()
            if file_id not in owned or target_id not in targets or not source:
                continue
            conn.execute(
                """
                INSERT INTO mapping_column_map
                  (mapping_file_id, target_column_id, source_column_name, transform_json)
                VALUES (?, ?, ?, ?)
                """,
                (file_id, target_id, source, json.dumps(item.get("transform") or {}, ensure_ascii=False)),
            )
    _touch(project_id)


def record_output(project_id: int, file_id: int, row_count: int, error_count: int) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO mapping_outputs (project_id, file_id, run_at, row_count, error_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, file_id, _now(), row_count, error_count),
        )
    _touch(project_id)


def list_runs(project_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM mapping_outputs WHERE project_id = ? ORDER BY id DESC",
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def clone_project(project_id: int) -> int | None:
    source = get_project(project_id)
    if source is None:
        return None
    new_id = create_project(f"{source['name']} copy", source.get("description") or "")
    column_ids: dict[int, int] = {}
    for column in source["columns"]:
        column_ids[int(column["id"])] = add_column(new_id, column["column_name"], column["data_type"])
    file_ids: dict[int, int] = {}
    for item in source["files"]:
        file_ids[int(item["id"])] = add_file(new_id, int(item["raw_file_id"]), item["sheet_name"], int(item["header_row"]))
    links = []
    for link in source["links"]:
        links.append(
            {
                "mapping_file_id": file_ids[int(link["mapping_file_id"])],
                "target_column_id": column_ids[int(link["target_column_id"])],
                "source": link["source_column_name"],
                "transform": json.loads(link.get("transform_json") or "{}"),
            }
        )
    save_links(new_id, links)
    return new_id


def _files(project_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT f.*, r.name AS raw_name, r.path AS raw_path
            FROM mapping_files f
            JOIN raw_files r ON r.id = f.raw_file_id
            WHERE f.project_id = ?
            ORDER BY f.id
            """,
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _columns(project_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM mapping_target_columns WHERE project_id = ? ORDER BY position, id",
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _links(project_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT m.* FROM mapping_column_map m
            JOIN mapping_files f ON f.id = m.mapping_file_id
            WHERE f.project_id = ?
            """,
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _last_output(project_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM mapping_outputs WHERE project_id = ? ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
    return dict(row) if row else None


def _touch(project_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE mapping_projects SET updated_at = ? WHERE id = ?", (_now(), project_id))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _saved_link(project_id: int, map_id: int) -> dict[str, Any] | None:
    project = get_project(project_id)
    if project is None:
        return None
    for view in link_views(project):
        if int(view["id"]) == map_id:
            return view
    return None


def _view_link(link: dict[str, Any], files: dict[int, dict[str, Any]], columns: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    item = files.get(int(link["mapping_file_id"]))
    column = columns.get(int(link["target_column_id"]))
    if item is None or column is None:
        return None
    raw = link.get("transform_json") or "{}"
    try:
        transform = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        transform = {}
    return {
        "id": int(link["id"]),
        "mapping_file_id": int(link["mapping_file_id"]),
        "target_column_id": int(column["id"]),
        "source_column_name": link["source_column_name"],
        "transform": transform if isinstance(transform, dict) else {},
        "raw_name": item["raw_name"],
        "sheet_name": item["sheet_name"],
        "target_name": column["column_name"],
        "data_type": column["data_type"],
    }


def _clean_transform(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "trim" in raw:
        out["trim"] = bool(raw.get("trim"))
    case = raw.get("case") or ""
    if case in {"lower", "upper"}:
        out["case"] = case
    date_format = str(raw.get("date_format") or "")
    if date_format:
        out["date_format"] = date_format[:40]
    number_format = str(raw.get("number_format") or "")
    if number_format in {"us", "eu", "dot", "plain"}:
        out["number_format"] = number_format
    for key in ("strip_dot", "strip_comma", "strip_currency"):
        if key in raw:
            out[key] = bool(raw.get(key))
    default = raw.get("default")
    if default not in (None, ""):
        out["default"] = str(default)[:200]
    return out
