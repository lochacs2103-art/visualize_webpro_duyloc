"""Thông tin cột và pivot. Đọc CSV bằng DuckDB, cache profile trong SQLite."""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.charts import _number, _numeric_sql
from app.database import connect
from app.filters import FilterError, FilterSpec, compile_where, parse_filter, quote_ident
from app.query_engine import json_safe

_AGGS = {"sum", "count", "avg", "min", "max"}
_FUNCS = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX"}


class AnalysisError(ValueError):
    def __init__(self) -> None:
        super().__init__("bad_analysis")


def column_profile(file_id: int, path: Path, columns: list[dict[str, str]]) -> list[dict[str, Any]]:
    mtime = path.stat().st_mtime
    cached = _read_profile(file_id, mtime, [column["name"] for column in columns])
    if cached is not None:
        return cached
    try:
        built = _duck_profile(path, columns)
    except Exception:
        built = _python_profile(path, columns)
    _write_profile(file_id, mtime, built)
    return built


def pivot_table(path: Path, columns: list[dict[str, str]], body: dict[str, Any]) -> dict[str, Any]:
    rows, cols, values, spec = _pivot_request(columns, body)
    try:
        return _duck_pivot(path, rows, cols, values, spec)
    except Exception:
        return _python_pivot(path, rows, cols, values, spec)


def list_pivots(file_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        found = conn.execute(
            "SELECT id, name, config_json, created_at FROM saved_pivots WHERE file_id = ? ORDER BY id DESC",
            (file_id,),
        ).fetchall()
    items = []
    for row in found:
        try:
            config = json.loads(row["config_json"])
        except json.JSONDecodeError:
            config = {}
        items.append({"id": row["id"], "name": row["name"], "config": config, "created_at": row["created_at"]})
    return items


def save_pivot(file_id: int, name: str, config: dict[str, Any]) -> int:
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO saved_pivots (file_id, name, config_json) VALUES (?, ?, ?)",
            (file_id, name.strip() or "Pivot", json.dumps(config, ensure_ascii=False)),
        )
        return int(cursor.lastrowid)


def delete_pivot(pivot_id: int) -> bool:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM saved_pivots WHERE id = ?", (pivot_id,))
        return cursor.rowcount > 0


def _read_profile(file_id: int, mtime: float, names: list[str]) -> list[dict[str, Any]] | None:
    with connect() as conn:
        rows = conn.execute(
            "SELECT column_name, profile_json FROM column_profiles WHERE file_id = ?",
            (file_id,),
        ).fetchall()
    if not rows:
        return None
    by_name = {}
    for row in rows:
        try:
            payload = json.loads(row["profile_json"])
        except json.JSONDecodeError:
            return None
        if abs(float(payload.get("source_mtime") or 0) - mtime) > 1:
            return None
        by_name[row["column_name"]] = payload
    if [name for name in names if name not in by_name]:
        return None
    return [_public(by_name[name]) for name in names]


def _write_profile(file_id: int, mtime: float, columns: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM column_profiles WHERE file_id = ?", (file_id,))
        for column in columns:
            stored = dict(column)
            stored["source_mtime"] = mtime
            conn.execute(
                "INSERT INTO column_profiles (file_id, column_name, profile_json) VALUES (?, ?, ?)",
                (file_id, column["name"], json.dumps(stored, ensure_ascii=False)),
            )


def _public(payload: dict[str, Any]) -> dict[str, Any]:
    shown = dict(payload)
    shown.pop("source_mtime", None)
    return shown


def _duck_profile(path: Path, columns: list[dict[str, str]]) -> list[dict[str, Any]]:
    import duckdb

    selects = ["count(*)"]
    for index, column in enumerate(columns):
        quoted = quote_ident(column["name"])
        blank = f"({quoted} IS NULL OR TRIM(CAST({quoted} AS VARCHAR)) = '')"
        selects.append(f"count(*) FILTER (WHERE {blank})")
        selects.append(f"count(DISTINCT {quoted}) FILTER (WHERE NOT {blank})")
        if column.get("type") == "number":
            number = _numeric_sql(quoted)
            selects.extend([f"MIN({number})", f"MAX({number})", f"AVG({number})", f"MEDIAN({number})", f"STDDEV_SAMP({number})"])
        elif column.get("type") == "date":
            day = f"TRY_CAST({quoted} AS DATE)"
            selects.extend([f"MIN({day})", f"MAX({day})", f"date_diff('day', MIN({day}), MAX({day}))"])
    con = duckdb.connect(database=":memory:")
    try:
        row = con.execute(
            f"WITH src AS (SELECT * FROM read_csv(?, header = true, auto_detect = true)) SELECT {', '.join(selects)} FROM src",
            [path.resolve().as_posix()],
        ).fetchone()
        built = []
        cursor = 1
        total = int(row[0] or 0)
        for column in columns:
            item = {"name": column["name"], "type": column.get("type") or "text", "rows": total, "empty": int(row[cursor] or 0), "distinct": int(row[cursor + 1] or 0)}
            cursor += 2
            if column.get("type") == "number":
                item.update({
                    "min": _round(row[cursor]),
                    "max": _round(row[cursor + 1]),
                    "mean": _round(row[cursor + 2]),
                    "median": _round(row[cursor + 3]),
                    "std": _round(row[cursor + 4]),
                })
                cursor += 5
            elif column.get("type") == "date":
                item.update({"min": _text(row[cursor]), "max": _text(row[cursor + 1]), "span_days": None if row[cursor + 2] is None else int(row[cursor + 2])})
                cursor += 3
            else:
                item["top"] = _duck_top(con, path, column["name"])
            built.append(item)
        return built
    finally:
        con.close()


def _duck_top(con: Any, path: Path, name: str) -> list[dict[str, Any]]:
    quoted = quote_ident(name)
    rows = con.execute(
        f"""
        WITH src AS (SELECT * FROM read_csv(?, header = true, auto_detect = true))
        SELECT CAST({quoted} AS VARCHAR), count(*)
        FROM src
        WHERE {quoted} IS NOT NULL AND TRIM(CAST({quoted} AS VARCHAR)) <> ''
        GROUP BY 1
        ORDER BY 2 DESC, 1
        LIMIT 5
        """,
        [path.resolve().as_posix()],
    ).fetchall()
    return [{"value": "" if row[0] is None else str(row[0]), "count": int(row[1])} for row in rows]


def _python_profile(path: Path, columns: list[dict[str, str]]) -> list[dict[str, Any]]:
    stats = {
        column["name"]: {"empty": 0, "values": Counter(), "numbers": [], "dates": []}
        for column in columns
    }
    total = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            reader.fieldnames = [(name or "").lstrip("\ufeff") for name in reader.fieldnames]
        for row in reader:
            total += 1
            for column in columns:
                name = column["name"]
                raw = row.get(name)
                if raw is None or str(raw).strip() == "":
                    stats[name]["empty"] += 1
                    continue
                text = str(raw).strip()
                stats[name]["values"][text] += 1
                if column.get("type") == "number":
                    number = _number(raw)
                    if number is not None:
                        stats[name]["numbers"].append(number)
                elif column.get("type") == "date":
                    stats[name]["dates"].append(text[:10])
    built = []
    for column in columns:
        name = column["name"]
        found = stats[name]
        item: dict[str, Any] = {
            "name": name,
            "type": column.get("type") or "text",
            "rows": total,
            "empty": found["empty"],
            "distinct": len(found["values"]),
        }
        if column.get("type") == "number" and found["numbers"]:
            nums = found["numbers"]
            item.update({
                "min": _round(min(nums)),
                "max": _round(max(nums)),
                "mean": _round(statistics.fmean(nums)),
                "median": _round(statistics.median(nums)),
                "std": _round(statistics.stdev(nums) if len(nums) > 1 else None),
            })
        elif column.get("type") == "date" and found["dates"]:
            ordered = sorted(found["dates"])
            item.update({"min": ordered[0], "max": ordered[-1], "span_days": _span(ordered[0], ordered[-1])})
        elif column.get("type") != "number":
            item["top"] = [{"value": value, "count": count} for value, count in found["values"].most_common(5)]
        built.append(item)
    return built


def _pivot_request(columns: list[dict[str, str]], body: dict[str, Any]) -> tuple[list[str], list[str], list[dict[str, str]], FilterSpec | None]:
    if not isinstance(body, dict):
        raise AnalysisError()
    known = {str(item["name"]) for item in columns if item.get("name")}
    rows = _names(body.get("rows"), known, 4)
    cols = _names(body.get("columns"), known, 1)
    raw_values = body.get("values") or []
    if not isinstance(raw_values, list) or not raw_values or len(raw_values) > 3:
        raise AnalysisError()
    values = []
    for item in raw_values:
        if not isinstance(item, dict):
            raise AnalysisError()
        column = str(item.get("column") or "")
        aggregate = str(item.get("aggregate") or "sum")
        if column not in known or aggregate not in _AGGS:
            raise AnalysisError()
        values.append({"column": column, "aggregate": aggregate})
    if not rows and not cols:
        raise AnalysisError()
    raw_filter = body.get("filter") or ""
    if isinstance(raw_filter, dict):
        raw_filter = json.dumps(raw_filter)
    try:
        spec = parse_filter(str(raw_filter), columns)
    except FilterError as exc:
        raise AnalysisError() from exc
    return rows, cols, values, spec


def _names(raw: object, known: set[str], limit: int) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > limit:
        raise AnalysisError()
    names = []
    for item in raw:
        name = str(item or "")
        if name not in known or name in names:
            raise AnalysisError()
        names.append(name)
    return names


def _duck_pivot(path: Path, rows: list[str], cols: list[str], values: list[dict[str, str]], spec: FilterSpec | None) -> dict[str, Any]:
    import duckdb

    where, params = compile_where(spec)
    headers: list[str] = []
    con = duckdb.connect(database=":memory:")
    try:
        if cols:
            quoted = quote_ident(cols[0])
            found = con.execute(
                f"""
                WITH src AS (SELECT * FROM read_csv(?, header = true, auto_detect = true))
                SELECT CAST({quoted} AS VARCHAR)
                FROM src
                {where}
                {"AND" if where else "WHERE"} {quoted} IS NOT NULL AND TRIM(CAST({quoted} AS VARCHAR)) <> ''
                GROUP BY 1
                ORDER BY 1
                LIMIT 20
                """,
                [path.resolve().as_posix(), *params],
            ).fetchall()
            headers = [str(row[0]) for row in found if row[0] is not None]
        chosen = _value_names(values, headers)
        group = ", ".join(quote_ident(name) for name in rows) or ""
        select_rows = ", ".join(f"CAST({quote_ident(name)} AS VARCHAR)" for name in rows)
        pieces = [select_rows] if select_rows else []
        sql_params = list(params)
        for value in values:
            for header in headers or [None]:
                pieces.append(_agg_sql(value, cols[0] if cols else "", header))
                if header is not None:
                    sql_params.append(header)
        order = ", ".join(str(index + 1) for index in range(len(rows))) or "1"
        sql = (
            "WITH src AS (SELECT * FROM read_csv(?, header = true, auto_detect = true)) "
            f"SELECT {', '.join(pieces)} FROM src {where} "
            f"{('GROUP BY ' + group) if group else ''} ORDER BY {order} LIMIT 500"
        )
        table = con.execute(sql, [path.resolve().as_posix(), *sql_params]).fetchall()
    finally:
        con.close()
    names = rows + chosen
    matrix = [[_cell(item) for item in row] for row in table]
    return {"columns": names, "rows": matrix}


def _value_names(values: list[dict[str, str]], headers: list[str]) -> list[str]:
    names = []
    for value in values:
        targets = headers or [""]
        for header in targets:
            label = f"{header} · {value['column']}" if header else value["column"]
            if sum(item["column"] == value["column"] for item in values) > 1:
                label = f"{label} ({value['aggregate']})"
            names.append(label)
    return names


def _agg_sql(value: dict[str, str], column: str, header: str | None) -> str:
    quoted = quote_ident(value["column"])
    number = _numeric_sql(quoted)
    expr = "COUNT(*)" if value["aggregate"] == "count" else f"{_FUNCS[value['aggregate']]}({number})"
    if header is None:
        return expr
    return f"{expr.split('(')[0]}(CASE WHEN CAST({quote_ident(column)} AS VARCHAR) = ? THEN {number if value['aggregate'] != 'count' else '1'} END)"


def _cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        return _round(value)
    return json_safe(value)


def _python_pivot(path: Path, rows: list[str], cols: list[str], values: list[dict[str, str]], spec: FilterSpec | None) -> dict[str, Any]:
    from app.filters import attach_bounds, row_matches

    attach_bounds(path, spec)
    buckets: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            reader.fieldnames = [(name or "").lstrip("\ufeff") for name in reader.fieldnames]
        for row in reader:
            cleaned = {key: json_safe(value) for key, value in row.items()}
            if not row_matches(cleaned, spec):
                continue
            key = tuple(str(cleaned.get(name) or "").strip() for name in rows)
            buckets[key].append(cleaned)
    headers = []
    if cols:
        seen = []
        for grouped in buckets.values():
            for row in grouped:
                label = str(row.get(cols[0]) or "").strip()
                if label and label not in seen:
                    seen.append(label)
        headers = sorted(seen)[:20]
    names = list(rows)
    if headers:
        names.extend(f"{header} · {value['column']}" for value in values for header in headers)
    else:
        names.extend(value["column"] for value in values)
    matrix = []
    for key in sorted(buckets):
        built: list[Any] = list(key)
        grouped = buckets[key]
        for value in values:
            targets = headers or [None]
            for header in targets:
                chosen = grouped
                if header is not None:
                    chosen = [row for row in grouped if str(row.get(cols[0]) or "").strip() == header]
                built.append(_aggregate(chosen, value))
        matrix.append(built)
    return {"columns": names, "rows": matrix[:500]}


def _aggregate(rows: list[dict[str, Any]], value: dict[str, str]) -> float | None:
    if value["aggregate"] == "count":
        return float(len(rows))
    nums = [number for number in (_number(row.get(value["column"])) for row in rows) if number is not None]
    if not nums:
        return None
    if value["aggregate"] == "sum":
        return _round(sum(nums))
    if value["aggregate"] == "avg":
        return _round(sum(nums) / len(nums))
    if value["aggregate"] == "min":
        return _round(min(nums))
    return _round(max(nums))


def _round(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if abs(number - round(number)) < 1e-6:
        return float(int(round(number)))
    return round(number, 2)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _span(start: str, end: str) -> int | None:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None
