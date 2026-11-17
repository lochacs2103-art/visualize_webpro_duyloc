"""Import DuckDB/Polars. Máy thiếu runtime vẫn vào được app, chỉ chậm hơn."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

HAS_DUCKDB = False
HAS_POLARS = False
HAS_PANDAS = False

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError as exc:
    logger.warning("DuckDB không tải được, mapping sẽ đi đường Python: %s", exc)

try:
    import polars  # noqa: F401

    HAS_POLARS = True
except ImportError as exc:
    logger.warning("Polars không tải được, dùng pandas: %s", exc)

try:
    import pandas  # noqa: F401

    HAS_PANDAS = True
except ImportError as exc:
    logger.warning("Pandas không tải được: %s", exc)


def log_status() -> None:
    logger.info("Runtime duckdb=%s polars=%s pandas=%s", HAS_DUCKDB, HAS_POLARS, HAS_PANDAS)
