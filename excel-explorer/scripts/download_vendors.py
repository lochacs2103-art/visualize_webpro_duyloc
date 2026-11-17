"""Tải ECharts và html2canvas một lần trên máy build. Máy đích không chạy script này."""

from __future__ import annotations

import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "static" / "vendor"
FILES = {
    "echarts/echarts.min.js": "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js",
    "html2canvas/html2canvas.min.js": "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js",
}


def main() -> None:
    for relative, url in FILES.items():
        dest = ROOT / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file() and dest.stat().st_size > 1000:
            print(f"giu {relative}")
            continue
        urllib.request.urlretrieve(url, dest)
        print(f"tai {relative}")


if __name__ == "__main__":
    main()
