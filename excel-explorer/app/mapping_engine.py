"""Gộp nhiều CSV đã map thành một file. DuckDB nếu có, không thì Python."""

from __future__ import annotations

import csv
import json
import logging
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.compat import HAS_DUCKDB
from app.config import CSV_DIR, LOG_DIR, MAPPED_DIR, from_rel, to_rel
from app.converter import _write_frame, _write_xlsx_sheet
from app.converter_errors import ConvertError
from app.database import delete_files, get_file, insert_files
from app.filenames import safe_stem, short_file_label, unique_path
from app.filters import quote_ident
from app.mapping_store import get_project, record_output
from app.rawfiles import header_names

logger = logging.getLogger(__name__)
_DATE_FMT = {
    "dd/mm/yyyy": "%d/%m/%Y",
    "yyyy-mm-dd": "%Y-%m-%d",
    "dd-mm-yyyy": "%d-%m-%Y",
    "mm/dd/yyyy": "%m/%d/%Y",
}


def suggest_mapping(source_cols: list[str], target_cols: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for target in target_cols:
        best, score = "", 0.0
        for source in source_cols:
            ratio = SequenceMatcher(None, _norm(target), _norm(source)).ratio()
            if ratio > score:
                best, score = source, ratio
        if score >= 0.8 and best:
            result[target] = best
    return result


def sum_column(project_id: int, column_name: str) -> dict[str, Any]:
    """Tổng một cột số theo từng file nguồn, ví dụ Số tiền của T10 và T11."""
    project = _need(project_id)
    column = next((item for item in project["columns"] if item["column_name"] == column_name), None)
    if column is None or column["data_type"] != "number":
        raise ConvertError("bad_column")
    linked = {
        int(link["mapping_file_id"])
        for link in project["links"]
        if int(link["target_column_id"]) == int(column["id"])
    }
    totals = _sum_by_file(project, column_name) if linked else {}
    rows: list[dict[str, Any]] = []
    grand = 0.0
    saw = False
    for item in project["files"]:
        if not int(item.get("is_active") or 0):
            continue
        missing = int(item["id"]) not in linked
        value = None if missing else totals.get(str(item["raw_name"]))
        if value is not None:
            grand += float(value)
            saw = True
        rows.append(
            {
                "label": short_file_label(str(item["raw_name"])),
                "name": item["raw_name"],
                "sheet": item["sheet_name"],
                "missing": missing,
                "text": _format_money(value),
            }
        )
    return {
        "column": column_name,
        "rows": rows,
        "grand": _format_money(grand if saw else None),
    }


def _sum_by_file(project: dict[str, Any], column_name: str) -> dict[str, float]:
    if HAS_DUCKDB:
        import duckdb

        union = _union_sql(project, None)
        if not union:
            return {}
        sql = f"SELECT _source_file, SUM({quote_ident(column_name)}) FROM ({union}) GROUP BY _source_file"
        con = duckdb.connect(database=":memory:")
        try:
            pairs = con.execute(sql).fetchall()
        finally:
            con.close()
        return {str(name): float(value) for name, value in pairs if value is not None}
    names = [column["column_name"] for column in project["columns"]] + ["_source_file", "_source_sheet"]
    index = names.index(column_name)
    file_index = names.index("_source_file")
    totals: dict[str, float] = {}
    for row in _python_rows(project, None)[0]:
        value = row[index]
        if value is None or value == "":
            continue
        key = str(row[file_index])
        totals[key] = totals.get(key, 0.0) + float(value)
    return totals


def _format_money(value: Any) -> str:
    if value is None:
        return "—"
    number = float(value)
    if abs(number - round(number)) < 1e-6:
        return f"{int(round(number)):,}".replace(",", ".")
    whole, frac = f"{number:,.2f}".split(".")
    return whole.replace(",", ".") + "," + frac


def preview_project(project_id: int) -> dict[str, Any]:
    project = _need(project_id)
    columns, rows, errors = _collect(project, 100)
    return {"columns": columns, "rows": rows, "error_rows": errors, "truncated": len(rows) >= 100}


def run_project(project_id: int, mode: str, on_progress: Any = None) -> dict[str, Any]:
    project = _need(project_id)
    if on_progress:
        on_progress(10, "map_convert")
    for item in project["files"]:
        if int(item.get("is_active") or 0):
            ensure_csv(item)
    columns = _output_names(project)
    if on_progress:
        on_progress(85, "map_union")
    dest, file_id, total, error_count = _write_output(project, mode, columns)
    if on_progress:
        on_progress(95, "map_write")
    record_output(project_id, file_id, total, error_count)
    return {"file_id": file_id, "row_count": total, "error_count": error_count, "path": to_rel(dest)}


def source_headers(item: dict[str, Any]) -> list[str]:
    path = from_rel(item["raw_path"])
    return header_names(path, str(item["sheet_name"]), int(item["header_row"] or 1))


def _collect(project: dict[str, Any], limit: int | None) -> tuple[list[str], list[list[Any]], int]:
    """limit None: không giữ dòng (chỉ để DuckDB tự ghi). limit 0: python sẽ tự ghi sau."""
    names = _output_names(project)
    if HAS_DUCKDB and limit != 0:
        return names, *_duck(project, names, limit)
    if limit == 0:
        return names, [], 0
    rows, _errors = _python_rows(project, None)
    names, rows = _collapse_rows(project, rows)
    if limit:
        rows = rows[: int(limit)]
    return names, rows, _count_error_rows(rows, project["columns"])


def _duck(project: dict[str, Any], names: list[str], limit: int | None) -> tuple[list[list[Any]], int]:
    import duckdb

    sql = _mapped_sql(project, limit)
    if not sql:
        return [], 0
    con = duckdb.connect(database=":memory:")
    try:
        cursor = con.execute(sql)
        rows = [list(row) for row in cursor.fetchall()]
    finally:
        con.close()
    errors = _count_error_rows(rows, project["columns"])
    return rows, errors


def _union_sql(project: dict[str, Any], limit: int | None, source: bool = True) -> str:
    selects = []
    for item in project["files"]:
        if not int(item.get("is_active") or 0):
            continue
        if not source and not _link_index(project, int(item["id"])):
            continue
        csv_path = ensure_csv(item)
        selects.append(_select_sql(item, project, csv_path, source))
    if not selects:
        return ""
    return " UNION ALL ".join(selects)


def _mapped_sql(project: dict[str, Any], limit: int | None) -> str:
    """VLOOKUP theo khóa. Không khóa thì chỉ lấy dòng của file đã nối cột, không kèm tên file nguồn."""
    union = _union_sql(project, None, source=False)
    if not union:
        return ""
    sql = _group_sql(project, union)
    if not _key_columns(project):
        checks = " OR ".join(_present(quote_ident(column["column_name"])) for column in project["columns"])
        if checks:
            sql = f"SELECT * FROM ({sql}) WHERE {checks}"
    if limit:
        sql = f"SELECT * FROM ({sql}) LIMIT {int(limit)}"
    return sql


def _output_names(project: dict[str, Any]) -> list[str]:
    return [column["column_name"] for column in project["columns"]]


def _key_columns(project: dict[str, Any]) -> list[dict[str, Any]]:
    providers = _providers(project)
    return [column for column in project["columns"] if len(providers.get(int(column["id"]), ())) >= 2]


def _group_sql(project: dict[str, Any], union: str) -> str:
    keys = _key_columns(project)
    if not keys:
        return union
    chosen: list[str] = []
    grouped: list[str] = []
    key_ids = {int(column["id"]) for column in keys}
    for column in project["columns"]:
        quoted = quote_ident(column["column_name"])
        if int(column["id"]) in key_ids:
            chosen.append(quoted)
            grouped.append(quoted)
        elif column["data_type"] == "number":
            chosen.append(f"SUM({quoted}) AS {quoted}")
        else:
            chosen.append(
                f"CASE WHEN COUNT(DISTINCT {quoted}) = 1 THEN MAX({quoted}) ELSE NULL END AS {quoted}"
            )
    where = " OR ".join(_present(quote_ident(column["column_name"])) for column in keys)
    order = ", ".join(quote_ident(column["column_name"]) for column in keys)
    return (
        f"WITH raw AS ({union}) SELECT {', '.join(chosen)} FROM raw "
        f"WHERE {where} GROUP BY {', '.join(grouped)} ORDER BY {order}"
    )


def _present(expr: str) -> str:
    return f"({expr} IS NOT NULL AND TRIM(CAST({expr} AS VARCHAR)) <> '')"


def _providers(project: dict[str, Any]) -> dict[int, set[int]]:
    found: dict[int, set[int]] = {}
    for link in project["links"]:
        found.setdefault(int(link["target_column_id"]), set()).add(int(link["mapping_file_id"]))
    return found


def _select_sql(item: dict[str, Any], project: dict[str, Any], csv_path: Path, source: bool = True) -> str:
    by_target = _link_index(project, int(item["id"]))
    parts = []
    for column in project["columns"]:
        link = by_target.get(int(column["id"]))
        expr = "NULL"
        if link:
            expr = _sql_expr(link["source_column_name"], column["data_type"], _transform(link))
        parts.append(f"{expr} AS {quote_ident(column['column_name'])}")
    if source:
        parts.append(f"{_quote(item['raw_name'])} AS _source_file")
        parts.append(f"{_quote(item['sheet_name'])} AS _source_sheet")
    return (
        f"SELECT {', '.join(parts)} FROM read_csv_auto({_quote(csv_path.resolve().as_posix())}, "
        "header=true, all_varchar=true)"
    )


def _sql_expr(source: str, data_type: str, transform: dict[str, Any]) -> str:
    expr = f"CAST({quote_ident(source)} AS VARCHAR)"
    for old, new in transform.get("replace") or []:
        expr = f"REPLACE({expr}, {_quote(str(old))}, {_quote(str(new))})"
    if transform.get("trim", True):
        expr = f"TRIM({expr})"
    case = transform.get("case")
    if case == "lower":
        expr = f"LOWER({expr})"
    elif case == "upper":
        expr = f"UPPER({expr})"
    if data_type == "number":
        if transform.get("strip_currency", True):
            expr = _strip_money(expr)
        expr = _number_sql(expr, transform)
        expr = f"TRY_CAST(NULLIF({expr}, '') AS DOUBLE)"
    elif data_type == "date":
        fmt = _DATE_FMT.get(transform.get("date_format") or "", transform.get("date_format") or "%Y-%m-%d")
        expr = f"TRY_STRPTIME(NULLIF({expr}, ''), {_quote(fmt)})"
    elif data_type == "boolean":
        expr = f"TRY_CAST(NULLIF({expr}, '') AS BOOLEAN)"
    default = transform.get("default")
    if default not in (None, ""):
        expr = f"COALESCE({expr}, {_quote(str(default))})"
    return expr


def _number_mode(transform: dict[str, Any]) -> str:
    style = str(transform.get("number_format") or "")
    if style in {"eu", "us", "dot", "plain"}:
        return style
    if transform.get("strip_dot") and transform.get("strip_comma"):
        return "eu"
    if transform.get("strip_comma"):
        return "us"
    if transform.get("strip_dot"):
        return "dot"
    return "us"


def _number_sql(expr: str, transform: dict[str, Any]) -> str:
    mode = _number_mode(transform)
    if mode == "eu":
        return f"REPLACE(REPLACE({expr}, '.', ''), ',', '.')"
    if mode == "dot":
        return f"REPLACE({expr}, '.', '')"
    if mode == "plain":
        return expr
    return f"REPLACE({expr}, ',', '')"


def _strip_money(expr: str) -> str:
    for token in ("VNĐ", "VND", "đ", " "):
        expr = f"REPLACE({expr}, {_quote(token)}, '')"
    return expr


def ensure_csv(item: dict[str, Any]) -> Path:
    raw_path = from_rel(item["raw_path"])
    sheet = str(item["sheet_name"])
    header_row = int(item["header_row"] or 1)
    stamp = {"mtime": raw_path.stat().st_mtime, "size": raw_path.stat().st_size, "header": header_row, "sheet": sheet}
    dest = MAPPED_DIR / f"{item['raw_file_id']}_{_sheet_key(sheet)}.csv"
    meta = dest.with_suffix(".meta.json")
    if dest.is_file() and meta.is_file():
        try:
            if json.loads(meta.read_text(encoding="utf-8")) == stamp:
                return dest
        except json.JSONDecodeError:
            pass
    _write_sheet(raw_path, sheet, header_row, dest)
    meta.write_text(json.dumps(stamp), encoding="utf-8")
    return dest


def _write_sheet(path: Path, sheet: str, header_row: int, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".xls":
        import pandas as pd

        frame = pd.read_excel(path, sheet_name=sheet, header=header_row - 1, engine="xlrd")
        _write_frame(frame, dest, sheet)
        return
    from openpyxl import load_workbook

    from app.converter import _SkipSheet

    workbook = load_workbook(filename=path, read_only=True, data_only=True)
    try:
        worksheet = next((item for item in workbook.worksheets if item.title == sheet), None)
        if worksheet is None:
            raise ConvertError("empty_file")
        try:
            _write_xlsx_sheet(worksheet, dest, header_row, None)
        except _SkipSheet as exc:
            raise ConvertError("header_past_end") from exc
    finally:
        workbook.close()


def _write_output(project: dict[str, Any], mode: str, columns: list[str]) -> tuple[Path, int, int, int]:
    day = datetime.now().strftime("%Y-%m-%d")
    folder = CSV_DIR / day
    stem = safe_stem(f"mapped_{project['name']}")
    previous = project.get("last_output")
    if previous and mode == "overwrite":
        record = get_file(int(previous["file_id"]))
        if record:
            try:
                from_rel(record["csv_path"]).unlink(missing_ok=True)
            except (OSError, ValueError):
                pass
            delete_files([int(record["id"])])
        dest = folder / f"{stem}.csv"
    elif previous and mode != "copy":
        raise ConvertError("map_exists")
    else:
        dest = unique_path(folder, stem, ".csv")
    if HAS_DUCKDB:
        _copy_duck(project, dest)
        rows, errors = _profile_duck(dest, project["columns"])
    else:
        logger.warning("Đang gộp mapping bằng Python vì không có DuckDB")
        rows, errors = _write_python(project, dest)
    schema = [{"name": name, "type": "text"} for name in columns]
    for column in project["columns"]:
        for item in schema:
            if item["name"] == column["column_name"]:
                item["type"] = column["data_type"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ids = insert_files(
        [
            {
                "name": dest.name,
                "original_path": to_rel(dest),
                "csv_path": to_rel(dest),
                "date_folder": day,
                "row_count": rows,
                "col_count": len(columns),
                "schema_json": json.dumps(schema, ensure_ascii=False),
                "uploaded_at": now,
            }
        ]
    )
    _log_errors(project["id"], errors)
    return dest, ids[0], rows, errors


def _copy_duck(project: dict[str, Any], dest: Path) -> None:
    import duckdb

    sql = _mapped_sql(project, None)
    dest.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(database=":memory:")
    try:
        con.execute(f"COPY ({sql}) TO {_quote(dest.resolve().as_posix())} (HEADER true, DELIMITER ',')")
    finally:
        con.close()


def _profile_duck(dest: Path, columns: list[dict[str, Any]]) -> tuple[int, int]:
    import duckdb

    typed = [column["column_name"] for column in columns if column["data_type"] in {"number", "date"}]
    con = duckdb.connect(database=":memory:")
    try:
        total = int(con.execute("SELECT count(*) FROM read_csv_auto(?)", [dest.resolve().as_posix()]).fetchone()[0])
        if not typed:
            return total, 0
        checks = " OR ".join(f"{quote_ident(name)} IS NULL" for name in typed)
        errors = int(con.execute(f"SELECT count(*) FROM read_csv_auto(?) WHERE {checks}", [dest.resolve().as_posix()]).fetchone()[0])
    finally:
        con.close()
    return total, errors


def _python_rows(project: dict[str, Any], limit: int | None) -> tuple[list[list[Any]], int]:
    rows: list[list[Any]] = []
    errors = 0
    for item in project["files"]:
        if not int(item.get("is_active") or 0):
            continue
        by_target = _link_index(project, int(item["id"]))
        if not by_target:
            continue
        path = ensure_csv(item)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                built, bad = _apply_row(source, item, project["columns"], by_target)
                rows.append(built)
                errors += int(bad)
                if limit and len(rows) >= limit:
                    return rows, errors
    return rows, errors


def _write_python(project: dict[str, Any], dest: Path) -> tuple[int, int]:
    rows, _errors = _python_rows(project, None)
    names, rows = _collapse_rows(project, rows)
    errors = _count_error_rows(rows, project["columns"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(names)
        writer.writerows(rows)
    return len(rows), errors


def _collapse_rows(project: dict[str, Any], rows: list[list[Any]]) -> tuple[list[str], list[list[Any]]]:
    """Một dòng cho mỗi giá trị khóa. Cột số thì cộng. Cột chữ chỉ giữ khi mọi dòng cùng một giá trị."""
    keys = _key_columns(project)
    wide = [column["column_name"] for column in project["columns"]] + ["_source_file", "_source_sheet"]
    target_names = [column["column_name"] for column in project["columns"]]
    if not keys:
        kept = [row[: len(target_names)] for row in rows if any(not _blank(value) for value in row[: len(target_names)])]
        return target_names, kept
    index = {name: position for position, name in enumerate(wide)}
    key_ids = {int(column["id"]) for column in keys}
    buckets: dict[tuple[str, ...], list[list[Any]]] = {}
    for row in rows:
        marker = tuple(_marker(row[index[column["column_name"]]]) or "" for column in keys)
        if not any(marker):
            continue
        buckets.setdefault(marker, []).append(row)
    collapsed: list[list[Any]] = []
    for marker in sorted(buckets):
        group = buckets[marker]
        built: list[Any] = []
        for column in project["columns"]:
            position = index[column["column_name"]]
            values = [item[position] for item in group if not _blank(item[position])]
            if int(column["id"]) in key_ids:
                built.append(marker[keys.index(column)] or None)
            elif column["data_type"] == "number":
                numbers = []
                for value in values:
                    try:
                        numbers.append(float(value))
                    except (TypeError, ValueError):
                        continue
                built.append(sum(numbers) if numbers else None)
            else:
                distinct = list(dict.fromkeys(_marker(value) for value in values))
                built.append(values[0] if len(distinct) == 1 else None)
        collapsed.append(built)
    return [column["column_name"] for column in project["columns"]], collapsed


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _marker(value: Any) -> str | None:
    if _blank(value):
        return None
    return str(value).strip()


def _apply_row(source: dict[str, Any], item: dict[str, Any], columns: list[dict[str, Any]], links: dict[int, dict[str, Any]]) -> tuple[list[Any], bool]:
    built: list[Any] = []
    bad = False
    for column in columns:
        link = links.get(int(column["id"]))
        raw = ""
        if link:
            raw = str(source.get(link["source_column_name"]) or "")
        value = _py_value(raw, column["data_type"], _transform(link) if link else {})
        if column["data_type"] in {"number", "date"} and raw.strip() and value in ("", None):
            bad = True
        built.append("" if value is None else value)
    built.append(item["raw_name"])
    built.append(item["sheet_name"])
    return built, bad


def _py_value(raw: str, data_type: str, transform: dict[str, Any]) -> Any:
    text = raw
    for old, new in transform.get("replace") or []:
        text = text.replace(str(old), str(new))
    if transform.get("trim", True):
        text = text.strip()
    if transform.get("case") == "lower":
        text = text.lower()
    elif transform.get("case") == "upper":
        text = text.upper()
    value: Any = text
    if data_type == "number":
        cleaned = text
        if transform.get("strip_currency", True):
            cleaned = cleaned.replace("VNĐ", "").replace("VND", "").replace("đ", "").replace(" ", "")
        mode = _number_mode(transform)
        if mode == "eu":
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif mode == "us":
            cleaned = cleaned.replace(",", "")
        elif mode == "dot":
            cleaned = cleaned.replace(".", "")
        try:
            value = float(cleaned) if cleaned else None
        except ValueError:
            value = None
    elif data_type == "date":
        fmt = _DATE_FMT.get(transform.get("date_format") or "", transform.get("date_format") or "%Y-%m-%d")
        try:
            value = datetime.strptime(text, fmt).date().isoformat() if text else None
        except ValueError:
            value = None
    elif data_type == "boolean":
        value = text.lower() in {"1", "true", "yes", "y"} if text else None
    if (value is None or value == "") and transform.get("default") not in (None, ""):
        return transform["default"]
    return value


def _count_error_rows(rows: list[list[Any]], columns: list[dict[str, Any]]) -> int:
    indexes = [index for index, column in enumerate(columns) if column["data_type"] in {"number", "date"}]
    return sum(1 for row in rows if any(row[index] in (None, "") for index in indexes))


def _link_index(project: dict[str, Any], mapping_file_id: int) -> dict[int, dict[str, Any]]:
    found = {}
    for link in project["links"]:
        if int(link["mapping_file_id"]) == mapping_file_id:
            found[int(link["target_column_id"])] = link
    return found


def _transform(link: dict[str, Any] | None) -> dict[str, Any]:
    if not link:
        return {}
    raw = link.get("transform_json") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _log_errors(project_id: int, error_count: int) -> None:
    if not error_count:
        return
    path = LOG_DIR / f"mapping_errors_{project_id}.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(sep=' ', timespec='seconds')} errors={error_count}\n")


def _need(project_id: int) -> dict[str, Any]:
    project = get_project(project_id)
    if project is None:
        raise ConvertError("not_found")
    return project


def _sheet_key(sheet: str) -> str:
    import hashlib

    return hashlib.sha1(sheet.encode("utf-8")).hexdigest()[:8]


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFD", value.lower().strip())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(text.replace("_", " ").replace("-", " ").split())


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
