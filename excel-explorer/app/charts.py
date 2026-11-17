"""Dữ liệu chart từ CSV đã lọc. DuckDB gom nhóm, không kéo cả bảng ra trình duyệt."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.database import connect
from app.filters import FilterError, FilterSpec, attach_bounds, compile_where, parse_filter, quote_ident, row_matches
from app.query_engine import json_safe

_TYPES = {"bar", "line", "pie", "scatter", "area"}
_AGGS = {"none", "sum", "count", "avg", "min", "max"}
_FUNCS = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX"}


class ChartError(ValueError):
    def __init__(self) -> None:
        super().__init__("bad_chart")


def chart_payload(path: Path, columns: list[dict[str, str]], body: dict[str, Any]) -> dict[str, Any]:
    chart_type, x_col, y_col, aggregate, top_n, spec = _request(columns, body)
    try:
        labels, values = _duck(path, chart_type, x_col, y_col, aggregate, top_n, spec)
    except Exception:
        labels, values = _python(path, chart_type, x_col, y_col, aggregate, top_n, spec)
    name = y_col or x_col
    return {"labels": labels, "series": [{"name": name, "data": values}]}


def number_bounds(path: Path, columns: list[dict[str, str]]) -> dict[str, dict[str, float | None]]:
    names = [column["name"] for column in columns if column.get("name")]
    if not names or not path.is_file():
        return {}
    try:
        return _duck_bounds(path, names)
    except Exception:
        return _python_bounds(path, names)


def show_colors(file_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT show_colors FROM column_prefs WHERE file_id = ? AND column_name = ''",
            (file_id,),
        ).fetchone()
    return bool(row and row["show_colors"])


def set_show_colors(file_id: int, enabled: bool) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO column_prefs (file_id, column_name, show_colors)
            VALUES (?, '', ?)
            ON CONFLICT(file_id, column_name) DO UPDATE SET show_colors = excluded.show_colors
            """,
            (file_id, int(enabled)),
        )


def list_charts(file_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, name, config_json, created_at FROM saved_charts WHERE file_id = ? ORDER BY id DESC",
            (file_id,),
        ).fetchall()
    found = []
    for row in rows:
        try:
            config = json.loads(row["config_json"])
        except json.JSONDecodeError:
            config = {}
        found.append({"id": row["id"], "name": row["name"], "config": config, "created_at": row["created_at"]})
    return found


def save_chart(file_id: int, name: str, config: dict[str, Any]) -> int:
    label = name.strip() or "Chart"
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO saved_charts (file_id, name, config_json) VALUES (?, ?, ?)",
            (file_id, label, json.dumps(config, ensure_ascii=False)),
        )
        return int(cursor.lastrowid)


def delete_chart(chart_id: int) -> bool:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM saved_charts WHERE id = ?", (chart_id,))
        return cursor.rowcount > 0


def _request(columns: list[dict[str, str]], body: dict[str, Any]) -> tuple[str, str, str, str, int, FilterSpec | None]:
    if not isinstance(body, dict):
        raise ChartError()
    chart_type = str(body.get("chart_type") or "")
    aggregate = str(body.get("aggregate") or "sum")
    x_col = str(body.get("x_col") or "")
    y_col = str(body.get("y_col") or "")
    known = {str(item["name"]): str(item.get("type") or "text") for item in columns if item.get("name")}
    if chart_type not in _TYPES or aggregate not in _AGGS or x_col not in known:
        raise ChartError()
    needs_y = aggregate != "count"
    if needs_y and y_col not in known:
        raise ChartError()
    if not needs_y:
        y_col = ""
    try:
        top_n = int(body.get("top_n") or 20)
    except (TypeError, ValueError) as exc:
        raise ChartError() from exc
    cap = 500 if chart_type == "scatter" or aggregate == "none" else 100
    top_n = min(max(top_n, 1), cap)
    raw_filter = body.get("filter") or ""
    if isinstance(raw_filter, dict):
        raw_filter = json.dumps(raw_filter)
    try:
        spec = parse_filter(str(raw_filter), columns)
    except FilterError as exc:
        raise ChartError() from exc
    return chart_type, x_col, y_col, aggregate, top_n, spec


def _duck(
    path: Path,
    chart_type: str,
    x_col: str,
    y_col: str,
    aggregate: str,
    top_n: int,
    spec: FilterSpec | None,
) -> tuple[list[str], list[float | None]]:
    import duckdb

    where, params = compile_where(spec)
    x = quote_ident(x_col)
    present = f"(CAST({x} AS VARCHAR) IS NOT NULL AND TRIM(CAST({x} AS VARCHAR)) <> '')"
    where = f"{where} AND {present}" if where else f"WHERE {present}"
    grouped = chart_type not in {"scatter"} and aggregate != "none"
    if not grouped:
        y_expr = "NULL" if not y_col else _numeric_sql(quote_ident(y_col))
        select = f"CAST({x} AS VARCHAR), {y_expr}"
        sql = f"SELECT {select} FROM src {where} LIMIT {int(top_n)}"
    else:
        if aggregate == "count":
            value = "COUNT(*)"
        else:
            value = f"{_FUNCS[aggregate]}({_numeric_sql(quote_ident(y_col))})"
        order = "1" if chart_type in {"line", "area"} else "2 DESC"
        sql = f"SELECT CAST({x} AS VARCHAR), {value} FROM src {where} GROUP BY 1 ORDER BY {order} LIMIT {int(top_n)}"
    con = duckdb.connect(database=":memory:")
    try:
        rows = con.execute(
            f"WITH src AS (SELECT * FROM read_csv(?, header = true, auto_detect = true)) {sql}",
            [path.resolve().as_posix(), *params],
        ).fetchall()
    finally:
        con.close()
    labels = ["" if row[0] is None else str(row[0]) for row in rows]
    values = [None if row[1] is None else float(row[1]) for row in rows]
    return labels, values


def _python(
    path: Path,
    chart_type: str,
    x_col: str,
    y_col: str,
    aggregate: str,
    top_n: int,
    spec: FilterSpec | None,
) -> tuple[list[str], list[float | None]]:
    grouped = chart_type not in {"scatter"} and aggregate != "none"
    attach_bounds(path, spec)
    buckets: dict[str, list[float]] = defaultdict(list)
    labels: list[str] = []
    values: list[float | None] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            reader.fieldnames = [(name or "").lstrip("\ufeff") for name in reader.fieldnames]
        for row in reader:
            cleaned = {key: json_safe(value) for key, value in row.items()}
            if not row_matches(cleaned, spec):
                continue
            label = str(cleaned.get(x_col) or "").strip()
            if not label:
                continue
            number = _number(cleaned.get(y_col)) if y_col else None
            if not grouped:
                if len(labels) >= top_n:
                    break
                labels.append(label)
                values.append(number)
                continue
            if number is not None or aggregate == "count":
                buckets[label].append(0.0 if number is None else number)
    if not grouped:
        return labels, values
    scored: list[tuple[str, float | None]] = []
    for label, nums in buckets.items():
        if aggregate == "count":
            scored.append((label, float(len(nums))))
        elif aggregate == "sum":
            scored.append((label, sum(nums)))
        elif aggregate == "avg":
            scored.append((label, sum(nums) / len(nums) if nums else None))
        elif aggregate == "min":
            scored.append((label, min(nums) if nums else None))
        else:
            scored.append((label, max(nums) if nums else None))
    if chart_type in {"line", "area"}:
        scored.sort(key=lambda item: item[0])
    else:
        scored.sort(key=lambda item: (item[1] is None, -(item[1] or 0)))
    scored = scored[:top_n]
    return [item[0] for item in scored], [item[1] for item in scored]


def _duck_bounds(path: Path, names: list[str]) -> dict[str, dict[str, float | None]]:
    import duckdb

    pieces = []
    for name in names:
        quoted = quote_ident(name)
        number = _numeric_sql(quoted)
        text = f"TRIM(CAST({quoted} AS VARCHAR))"
        pieces.append(f"SUM(CASE WHEN {text} <> '' THEN 1 ELSE 0 END)")
        pieces.append(f"SUM(CASE WHEN {number} IS NOT NULL THEN 1 ELSE 0 END)")
        pieces.append(f"MIN({number})")
        pieces.append(f"MAX({number})")
    con = duckdb.connect(database=":memory:")
    try:
        row = con.execute(
            f"""
            WITH src AS (SELECT * FROM read_csv(?, header = true, auto_detect = true))
            SELECT {", ".join(pieces)} FROM src
            """,
            [path.resolve().as_posix()],
        ).fetchone()
    finally:
        con.close()
    found: dict[str, dict[str, float | None]] = {}
    for index, name in enumerate(names):
        filled = int(row[index * 4] or 0)
        numeric = int(row[index * 4 + 1] or 0)
        if filled == 0 or numeric / filled < 0.8:
            continue
        low = row[index * 4 + 2]
        high = row[index * 4 + 3]
        found[name] = {
            "min": None if low is None else float(low),
            "max": None if high is None else float(high),
        }
    return found


def _python_bounds(path: Path, names: list[str]) -> dict[str, dict[str, float | None]]:
    stats = {name: {"min": None, "max": None, "filled": 0, "numeric": 0} for name in names}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            reader.fieldnames = [(name or "").lstrip("\ufeff") for name in reader.fieldnames]
        for row in reader:
            for name in names:
                raw = row.get(name)
                if raw is None or str(raw).strip() == "":
                    continue
                stats[name]["filled"] += 1
                number = _number(raw)
                if number is None:
                    continue
                stats[name]["numeric"] += 1
                low = stats[name]["min"]
                high = stats[name]["max"]
                stats[name]["min"] = number if low is None or number < low else low
                stats[name]["max"] = number if high is None or number > high else high
    found: dict[str, dict[str, float | None]] = {}
    for name, item in stats.items():
        if item["filled"] and item["numeric"] / item["filled"] >= 0.8:
            found[name] = {"min": item["min"], "max": item["max"]}
    return found


def _numeric_sql(quoted: str) -> str:
    """Đọc số kể cả khi ô là chữ có dấu phẩy hoặc dấu chấm ngăn cách hàng nghìn."""
    text = f"TRIM(CAST({quoted} AS VARCHAR))"
    for token in (" ", "₫", "đ", "VND"):
        text = f"replace({text}, '{token}', '')"
    return f"""TRY_CAST(
      CASE
        WHEN strpos({text}, ',') > 0 AND strpos({text}, '.') > 0 AND strpos({text}, ',') > strpos({text}, '.')
          THEN replace(replace({text}, '.', ''), ',', '.')
        WHEN strpos({text}, ',') > 0 AND strpos({text}, '.') > 0
          THEN replace({text}, ',', '')
        WHEN regexp_matches({text}, '^-?[0-9]{{1,3}}(,[0-9]{{3}})+([.][0-9]+)?$')
          THEN replace({text}, ',', '')
        WHEN regexp_matches({text}, '^-?[0-9]{{1,3}}([.][0-9]{{3}})+([,][0-9]+)?$')
          THEN replace(replace({text}, '.', ''), ',', '.')
        WHEN regexp_matches({text}, '^-?[0-9]+,[0-9]+$')
          THEN replace({text}, ',', '.')
        ELSE {text}
      END AS DOUBLE)"""


def _number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(" ", "").replace("₫", "").replace("đ", "").replace("VND", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        text = text.replace(",", "") if len(parts) > 2 or (len(parts[-1]) == 3 and len(parts[0]) <= 3) else text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None
