"""Sinh SQL tổng hợp từ cấu hình UI. Chỉ nhận cột có trong file."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.config import CSV_DIR, from_rel, to_rel
from app.database import get_file, insert_files, workbook_name
from app.filenames import safe_stem, unique_path
from app.filters import quote_ident

logger = logging.getLogger(__name__)

_FUNCS = {"SUM", "COUNT", "AVG", "MIN", "MAX"}
_FILTER_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "is_null", "is_not_null"}
_CMP = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


class StudioError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def preview(file_id: int, config: dict[str, Any]) -> dict[str, Any]:
    record, columns = _record(file_id)
    sql = _sql(config, columns, _csv_path(record), 100)
    rows, names = _query(sql)
    return {"columns": names, "rows": rows, "error": ""}


def save(file_id: int, config: dict[str, Any]) -> dict[str, Any]:
    record, columns = _record(file_id)
    path = _csv_path(record)
    sql = _sql(config, columns, path, None)
    selected = _selected(config, columns)
    day = datetime.now().strftime("%Y-%m-%d")
    stem = safe_stem(f"studio_{Path(workbook_name(record)).stem}")
    dest = unique_path(CSV_DIR / day, stem, ".csv")
    _copy(sql, dest)
    total = _count(dest)
    schema = [{"name": name, "type": kind} for name, kind in selected] or [
        {"name": name, "type": "text"} for name in _header(dest)
    ]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ids = insert_files(
        [
            {
                "name": dest.name,
                "original_path": to_rel(dest),
                "csv_path": to_rel(dest),
                "date_folder": day,
                "row_count": total,
                "col_count": len(schema),
                "schema_json": json.dumps(schema, ensure_ascii=False),
                "uploaded_at": now,
            }
        ]
    )
    return {"file_id": ids[0], "row_count": total}


def column_list(record: dict[str, Any]) -> list[dict[str, str]]:
    try:
        raw = json.loads(record.get("schema_json") or "[]")
    except json.JSONDecodeError:
        raw = []
    columns = []
    for item in raw:
        if isinstance(item, dict) and item.get("name"):
            columns.append({"name": str(item["name"]), "type": str(item.get("type") or "text")})
    return columns


def _record(file_id: int) -> tuple[dict[str, Any], list[dict[str, str]]]:
    record = get_file(file_id)
    if record is None:
        raise StudioError("not_found")
    columns = column_list(record)
    if not columns:
        raise StudioError("bad_config")
    return record, columns


def _csv_path(record: dict[str, Any]) -> Path:
    try:
        path = from_rel(str(record.get("csv_path") or ""))
    except ValueError as exc:
        raise StudioError("missing_csv") from exc
    if not path.is_file():
        raise StudioError("missing_csv")
    return path


def _sql(config: dict[str, Any], columns: list[dict[str, str]], path: Path, limit: int | None) -> str:
    if not isinstance(config, dict):
        raise StudioError("bad_config")
    known = {item["name"]: item["type"] for item in columns}
    select, group_sql, where_sql = _clauses(config, known)
    source = f"read_csv({_quote(path.resolve().as_posix())}, header=true, auto_detect=true)"
    sql = f"SELECT {select} FROM {source}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    if group_sql:
        sql += f" GROUP BY {group_sql}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return sql


def _clauses(config: dict[str, Any], known: dict[str, str]) -> tuple[str, str, str]:
    groups = _names(config.get("group_by"), known, 12)
    aggs = _aggs(config.get("aggregations"), known)
    formulas = _formulas(config.get("formulas"), known)
    where_sql = _where(config.get("filters"), known)
    if groups or aggs:
        pieces: list[str] = [quote_ident(name) for name in groups]
        pieces.extend(f"{expr} AS {quote_ident(alias)}" for expr, alias, _kind in aggs)
        pieces.extend(f"({expr}) AS {quote_ident(alias)}" for expr, alias in formulas)
        if not pieces:
            raise StudioError("bad_config")
        return ", ".join(pieces), ", ".join(quote_ident(name) for name in groups), where_sql
    select = "*"
    if formulas:
        extra = ", ".join(f"({expr}) AS {quote_ident(alias)}" for expr, alias in formulas)
        select = f"*, {extra}"
    return select, "", where_sql


def _selected(config: dict[str, Any], columns: list[dict[str, str]]) -> list[tuple[str, str]]:
    known = {item["name"]: item["type"] for item in columns}
    groups = _names(config.get("group_by"), known, 12)
    aggs = _aggs(config.get("aggregations"), known)
    formulas = _formulas(config.get("formulas"), known)
    if groups or aggs:
        found = [(name, known.get(name, "text")) for name in groups]
        found.extend((alias, kind) for _expr, alias, kind in aggs)
        found.extend((alias, "number") for _expr, alias in formulas)
        return found
    found = [(item["name"], item["type"]) for item in columns]
    found.extend((alias, "number") for _expr, alias in formulas)
    return found


def _names(raw: Any, known: dict[str, str], limit: int) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > limit:
        raise StudioError("bad_config")
    names = []
    for item in raw:
        name = str(item or "")
        if name not in known:
            raise StudioError("bad_column")
        if name not in names:
            names.append(name)
    return names


def _aggs(raw: Any, known: dict[str, str]) -> list[tuple[str, str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 12:
        raise StudioError("bad_config")
    found = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise StudioError("bad_config")
        column = str(item.get("column") or "")
        func = str(item.get("func") or "").upper()
        if column not in known or func not in _FUNCS:
            raise StudioError("bad_column")
        alias = _alias(str(item.get("alias") or ""), f"{func} {column}")
        if alias in seen:
            raise StudioError("bad_alias")
        seen.add(alias)
        kind = "number" if func in {"SUM", "COUNT", "AVG"} else known[column]
        found.append((f"{func}({quote_ident(column)})", alias, kind))
    return found


def _formulas(raw: Any, known: dict[str, str]) -> list[tuple[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 8:
        raise StudioError("bad_config")
    found = []
    for item in raw:
        if not isinstance(item, dict):
            raise StudioError("bad_formula")
        expression = str(item.get("expression") or "").strip()
        if not expression:
            continue
        alias = _alias(str(item.get("alias") or ""), "Công thức")
        found.append((_expression(expression, set(known)), alias))
    return found


def _where(raw: Any, known: dict[str, str]) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, list) or len(raw) > 20:
        raise StudioError("bad_config")
    parts = []
    for item in raw:
        if not isinstance(item, dict):
            raise StudioError("bad_config")
        column = str(item.get("column") or "")
        op = str(item.get("op") or "")
        if column not in known or op not in _FILTER_OPS:
            raise StudioError("bad_column")
        ident = quote_ident(column)
        if op in {"is_null", "is_not_null"}:
            parts.append(f"{ident} IS {'NULL' if op == 'is_null' else 'NOT NULL'}")
            continue
        value = "" if item.get("value") is None else str(item.get("value"))
        if value.strip() == "":
            continue
        if op == "contains":
            parts.append(f"CAST({ident} AS VARCHAR) ILIKE {_quote(_like(value))} ESCAPE '\\'")
        else:
            parts.append(f"CAST({ident} AS VARCHAR) {_CMP[op]} {_quote(value)}")
    return " AND ".join(parts)


def _expression(expr: str, names: set[str]) -> str:
    if len(expr) > 240:
        raise StudioError("bad_formula")
    tokens = _tokenize(expr, names)
    parts: list[str] = []
    index = 0
    while index < len(tokens):
        kind, value = tokens[index]
        if kind == "num":
            parts.append(value)
        elif kind == "op":
            parts.append(value)
        elif kind == "name":
            parts.append(quote_ident(value))
        elif kind == "func":
            if index + 3 >= len(tokens) or tokens[index + 1] != ("op", "(") or tokens[index + 3] != ("op", ")"):
                raise StudioError("bad_formula")
            arg_kind, arg = tokens[index + 2]
            if value == "COUNT" and arg_kind == "op" and arg == "*":
                parts.append("COUNT(*)")
            elif arg_kind == "name":
                parts.append(f"{value}({quote_ident(arg)})")
            else:
                raise StudioError("bad_formula")
            index += 4
            continue
        else:
            raise StudioError("bad_formula")
        index += 1
    if not parts:
        raise StudioError("bad_formula")
    return " ".join(parts)


def _tokenize(expr: str, names: set[str]) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    ordered = sorted(names, key=len, reverse=True)
    index = 0
    while index < len(expr):
        if expr[index].isspace():
            index += 1
            continue
        if expr[index] in "+-*/()":
            tokens.append(("op", expr[index]))
            index += 1
            continue
        number = _number(expr, index)
        if number:
            tokens.append(("num", number[0]))
            index = number[1]
            continue
        word = re.match(r"[A-Za-z]+", expr[index:])
        if word and word.group(0).upper() in _FUNCS:
            nxt = index + len(word.group(0))
            if nxt < len(expr) and expr[nxt] == "(":
                tokens.append(("func", word.group(0).upper()))
                index = nxt
                continue
        matched = False
        for name in ordered:
            if not expr.startswith(name, index):
                continue
            nxt = index + len(name)
            if nxt < len(expr) and (expr[nxt].isalnum() or expr[nxt] == "_"):
                continue
            tokens.append(("name", name))
            index = nxt
            matched = True
            break
        if not matched:
            raise StudioError("bad_formula")
    return tokens


def _number(expr: str, index: int) -> tuple[str, int] | None:
    if not expr[index].isdigit():
        return None
    end = index
    dot = False
    while end < len(expr) and (expr[end].isdigit() or (expr[end] == "." and not dot)):
        if expr[end] == ".":
            dot = True
        end += 1
    if expr[end - 1] == ".":
        return None
    return expr[index:end], end


def _alias(alias: str, fallback: str) -> str:
    text = (alias or fallback).strip()
    if not text or len(text) > 80 or any(ord(char) < 32 for char in text):
        raise StudioError("bad_alias")
    return text


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _quote(value: str) -> str:
    if "\x00" in value:
        raise StudioError("bad_config")
    return "'" + value.replace("'", "''") + "'"


def _query(sql: str) -> tuple[list[list[Any]], list[str]]:
    try:
        import duckdb
    except ImportError as exc:
        logger.warning("Data Studio không có DuckDB: %s", exc)
        raise StudioError("studio_unavailable") from exc
    con = duckdb.connect(database=":memory:")
    try:
        cursor = con.execute(sql)
        names = [item[0] for item in cursor.description]
        rows = [[_cell(value) for value in row] for row in cursor.fetchall()]
    finally:
        con.close()
    return rows, names


def _copy(sql: str, dest: Path) -> None:
    try:
        import duckdb
    except ImportError as exc:
        logger.warning("Data Studio không có DuckDB: %s", exc)
        raise StudioError("studio_unavailable") from exc
    dest.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(database=":memory:")
    try:
        con.execute(f"COPY ({sql}) TO {_quote(dest.resolve().as_posix())} (HEADER true, DELIMITER ',')")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        con.close()


def _count(path: Path) -> int:
    rows, _names = _query(f"SELECT count(*) FROM read_csv({_quote(path.resolve().as_posix())}, header=true)")
    return int(rows[0][0]) if rows else 0


def _header(path: Path) -> list[str]:
    _rows, names = _query(f"SELECT * FROM read_csv({_quote(path.resolve().as_posix())}, header=true) LIMIT 0")
    return names


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)
