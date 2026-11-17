"""Biên dịch bộ lọc UI thành mệnh đề WHERE cho DuckDB. Không nhận SQL thô."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

_OPS = {"eq", "ne", "gt", "lt", "contains", "starts_with", "between", "is_null", "is_not_null", "min", "max", "none"}
_VALUE_OPS = {"eq", "ne", "gt", "lt", "contains", "starts_with", "between"}


class FilterError(ValueError):
    def __init__(self) -> None:
        super().__init__("bad_filter")


@dataclass
class Rule:
    column: str
    op: str
    value: str = ""
    value2: str = ""
    col_type: str = "text"
    bound: object = None


@dataclass
class FilterSpec:
    logic: str = "and"
    rules: list[Rule] = field(default_factory=list)


def parse_filter(raw: str | None, columns: list[dict[str, str]]) -> FilterSpec | None:
    """`raw` là JSON. Rỗng nghĩa là không lọc."""
    if raw is None or not str(raw).strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FilterError() from exc
    if not isinstance(payload, dict):
        raise FilterError()
    known = {str(item["name"]): str(item.get("type") or "text") for item in columns if item.get("name")}
    logic = payload.get("logic") or "and"
    if logic not in {"and", "or"}:
        raise FilterError()
    incoming = payload.get("rules") or []
    if not isinstance(incoming, list) or len(incoming) > 20:
        raise FilterError()
    rules: list[Rule] = []
    for item in incoming:
        if not isinstance(item, dict):
            raise FilterError()
        column = str(item.get("column") or "")
        op = str(item.get("op") or "")
        if column not in known or op not in _OPS:
            raise FilterError()
        value = "" if item.get("value") is None else str(item.get("value"))
        value2 = "" if item.get("value2") is None else str(item.get("value2"))
        if op == "none":
            continue
        if op in _VALUE_OPS and value.strip() == "":
            continue
        if op == "between" and value2.strip() == "":
            continue
        rules.append(Rule(column, op, value, value2, known[column]))
    if not rules:
        return None
    return FilterSpec(logic, rules)


def attach_bounds(path: Path, spec: FilterSpec | None) -> None:
    """Gắn min/max thật của cột khi không dùng DuckDB. DuckDB tự tính trong câu WHERE."""
    if spec is None or not any(rule.op in {"min", "max"} for rule in spec.rules):
        return
    stats: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            reader.fieldnames = [(name or "").lstrip("\ufeff") for name in reader.fieldnames]
        for row in reader:
            for rule in spec.rules:
                if rule.op not in {"min", "max"}:
                    continue
                current = _python_value(row.get(rule.column), rule.col_type)
                if current is None or current == "":
                    continue
                found = stats.setdefault(rule.column, {})
                low = found.get("min")
                high = found.get("max")
                found["min"] = current if low is None or current < low else low
                found["max"] = current if high is None or current > high else high
    for rule in spec.rules:
        if rule.op in {"min", "max"}:
            rule.bound = stats.get(rule.column, {}).get(rule.op)


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def compile_where(spec: FilterSpec | None) -> tuple[str, list[object]]:
    if spec is None or not spec.rules:
        return "", []
    parts: list[str] = []
    params: list[object] = []
    for rule in spec.rules:
        sql, extra = _rule_sql(rule)
        parts.append(sql)
        params.extend(extra)
    joiner = " OR " if spec.logic == "or" else " AND "
    return "WHERE " + joiner.join(parts), params


def row_matches(row: dict[str, object], spec: FilterSpec | None) -> bool:
    if spec is None or not spec.rules:
        return True
    checks = [_match_value(row.get(rule.column), rule) for rule in spec.rules]
    return any(checks) if spec.logic == "or" else all(checks)


def _rule_sql(rule: Rule) -> tuple[str, list[object]]:
    quoted = quote_ident(rule.column)
    text = f"CAST({quoted} AS VARCHAR)"
    if rule.op == "is_null":
        return f"({quoted} IS NULL OR {text} = '')", []
    if rule.op == "is_not_null":
        return f"({quoted} IS NOT NULL AND {text} <> '')", []
    left = _typed(quoted, rule.col_type)
    if rule.op in {"min", "max"}:
        fn = "MIN" if rule.op == "min" else "MAX"
        return f"{left} = (SELECT {fn}({left}) FROM src)", []
    if rule.op == "contains":
        return f"{text} ILIKE '%' || ? || '%' ESCAPE '\\'", [_like(rule.value)]
    if rule.op == "starts_with":
        return f"{text} ILIKE ? || '%' ESCAPE '\\'", [_like(rule.value)]
    if rule.op == "between":
        return f"{left} BETWEEN ? AND ?", [_coerce(rule.value, rule.col_type), _coerce(rule.value2, rule.col_type)]
    symbol = {"eq": "=", "ne": "<>", "gt": ">", "lt": "<"}[rule.op]
    return f"{left} {symbol} ?", [_coerce(rule.value, rule.col_type)]


def _typed(quoted: str, col_type: str) -> str:
    if col_type == "number":
        return f"TRY_CAST({quoted} AS DOUBLE)"
    if col_type == "date":
        return f"TRY_CAST({quoted} AS DATE)"
    return f"CAST({quoted} AS VARCHAR)"


def _coerce(value: str, col_type: str) -> object:
    if col_type == "number":
        try:
            return float(value.replace(",", ""))
        except ValueError as exc:
            raise FilterError() from exc
    return value.strip()


def _like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _match_value(value: object, rule: Rule) -> bool:
    empty = value is None or str(value).strip() == ""
    if rule.op == "is_null":
        return empty
    if rule.op == "is_not_null":
        return not empty
    if rule.op in {"min", "max"}:
        left_bound = _python_value(value, rule.col_type)
        return left_bound is not None and left_bound == rule.bound
    text = "" if value is None else str(value)
    if rule.op == "contains":
        return rule.value.casefold() in text.casefold()
    if rule.op == "starts_with":
        return text.casefold().startswith(rule.value.casefold())
    left = _python_value(value, rule.col_type)
    right = _coerce(rule.value, rule.col_type)
    if left is None or (rule.col_type == "number" and isinstance(left, str)):
        return False
    if rule.op == "between":
        upper = _coerce(rule.value2, rule.col_type)
        return right <= left <= upper
    if rule.op == "eq":
        return left == right
    if rule.op == "ne":
        return left != right
    if rule.op == "gt":
        return left > right
    return left < right


def _python_value(value: object, col_type: str) -> object:
    if value is None:
        return None
    if col_type == "number":
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            return None
    return str(value).strip()
