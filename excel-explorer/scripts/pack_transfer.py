"""Tách bản chạy thành từng gói dưới 25 MB, kèm note để lần sau chỉ gửi phần đổi.

File gửi đi không có đuôi .exe hay .zip. Máy đích dùng tar có sẵn của Windows.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dist" / "excel-explorer"
OUT_DIR = ROOT.parent / "chuyen-may"
NOTE_DIR = ROOT.parent / "note"
CHUNK = 24_000_000

RENAME = {
    "excel-explorer.exe": "excel-explorer.app",
    "vc_redist.x64.exe": "vc_redist.x64.app",
    "_internal/base_library.zip": "_internal/base_library.dat",
}
SKIP = ("data/", "logs/")

GROUP_INFO = {
    "app": (
        "Chương trình",
        "Code Python của app đã đóng vào file chạy: mapping, chart, pivot, upload, server.",
        "Sửa code Python trên máy này, build lại exe, rồi gửi file của nhóm này.",
    ),
    "static": (
        "Giao diện",
        "JS, CSS, icon, ECharts, html2canvas trong static.",
        "Sửa file trong thư mục static.",
    ),
    "templates": (
        "Trang HTML",
        "Template Jinja trong templates.",
        "Sửa file HTML trong thư mục templates.",
    ),
    "vc": (
        "Visual C++",
        "Bộ cài Visual C++ runtime, dùng khi máy kia chưa có.",
        "Gần như không đổi. Chỉ gửi lại khi mình nói.",
    ),
    "polars": (
        "Polars",
        "File máy của Polars, _polars_runtime.pyd, và file nhỏ đi kèm nếu có.",
        "Khi nâng thư viện Polars.",
    ),
    "polars-py": (
        "Polars Python",
        "Code Python của thư viện Polars.",
        "Khi nâng thư viện Polars.",
    ),
    "duckdb": (
        "DuckDB",
        "File máy _duckdb.pyd.",
        "Khi nâng DuckDB.",
    ),
    "duckdb-py": (
        "DuckDB Python",
        "Code Python của thư viện DuckDB.",
        "Khi nâng DuckDB.",
    ),
    "pandas": (
        "Pandas",
        "Thư viện pandas.",
        "Khi nâng pandas.",
    ),
    "numpy": (
        "NumPy",
        "Thư viện numpy và OpenBLAS.",
        "Khi nâng numpy.",
    ),
    "runtime": (
        "Phần còn lại",
        "Python, FastAPI, Uvicorn, OpenPyXL, Pydantic, Watchdog, base_library và DLL hệ thống.",
        "Khi nâng Python hoặc các thư viện nhỏ này.",
    ),
}

RUN_BAT = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Excel Explorer

if not exist "%~dp0excel-explorer.exe" (
    if exist "%~dp0excel-explorer.app" copy /Y "%~dp0excel-explorer.app" "%~dp0excel-explorer.exe" >nul
)
if not exist "%~dp0vc_redist.x64.exe" (
    if exist "%~dp0vc_redist.x64.app" copy /Y "%~dp0vc_redist.x64.app" "%~dp0vc_redist.x64.exe" >nul
)
if not exist "%~dp0_internal\base_library.zip" (
    if exist "%~dp0_internal\base_library.dat" copy /Y "%~dp0_internal\base_library.dat" "%~dp0_internal\base_library.zip" >nul
)

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 (
    start "" "http://127.0.0.1:8000"
    exit /b 0
)

reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Installed >nul 2>&1
if errorlevel 1 (
    if exist "%~dp0vc_redist.x64.exe" (
        echo Dang cai Visual C++ Runtime...
        "%~dp0vc_redist.x64.exe" /install /quiet /norestart
    )
)

start "Excel Explorer" "%~dp0excel-explorer.exe"
"""


def group_of(rel: str) -> str | None:
    if rel.startswith(SKIP) or rel == "run.bat":
        return None
    if rel == "excel-explorer.exe":
        return "app"
    if rel == "vc_redist.x64.exe":
        return "vc"
    if rel.startswith("_internal/_polars_runtime_32/"):
        return "polars"
    if rel == "_internal/_duckdb.pyd":
        return "duckdb"
    if rel.startswith("_internal/static/"):
        return "static"
    if rel.startswith("_internal/templates/"):
        return "templates"
    name = rel.split("/")[1] if rel.startswith("_internal/") else ""
    if name == "pandas" or name.startswith("pandas"):
        return "pandas"
    if name == "numpy" or name.startswith("numpy"):
        return "numpy"
    if name == "polars" or name.startswith("polars"):
        return "polars-py"
    if name == "duckdb" or name.startswith("duckdb"):
        return "duckdb-py"
    return "runtime"


def stored_rel(rel: str) -> str:
    return RENAME.get(rel, rel)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_tar(path: Path, pairs: list[tuple[Path, str]]) -> int:
    def reset(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.mtime = 0
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        return info

    with tarfile.open(path, "w:gz", compresslevel=6) as tar:
        for src, arc in pairs:
            if src is None:
                data = arc.encode("utf-8") if False else b""
            tar.add(src, arcname=arc, filter=reset)
    return path.stat().st_size


def write_tar_bytes(path: Path, blobs: list[tuple[bytes, str]]) -> int:
    with tarfile.open(path, "w:gz", compresslevel=6) as tar:
        for data, arc in blobs:
            info = tarfile.TarInfo(arc)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return path.stat().st_size


def split_pairs(pairs: list[tuple[Path, str]]) -> tuple[list, list]:
    sizes = [src.stat().st_size for src, _ in pairs]
    total = sum(sizes)
    running = 0
    cut = 1
    for index, size in enumerate(sizes[:-1], start=1):
        running += size
        cut = index
        if running >= total / 2:
            break
    return pairs[:cut], pairs[cut:]


def emit_tars(group: str, pairs: list[tuple[Path, str]]) -> list[Path]:
    """Trả về các file .pack đã ghi, mỗi file không quá 24 MB."""
    chunks: list[list[tuple[Path, str]]] = []

    def divide(items: list[tuple[Path, str]]) -> None:
        trial = OUT_DIR / "_trial.pack"
        size = write_tar(trial, items)
        trial.unlink()
        if size <= CHUNK:
            chunks.append(items)
            return
        if len(items) == 1:
            raise SystemExit(f"{group} có một file nén vẫn quá 25 MB")
        left, right = split_pairs(items)
        divide(left)
        divide(right)

    divide(pairs)
    written: list[Path] = []
    for index, items in enumerate(chunks, start=1):
        label = f"{group}.pack" if len(chunks) == 1 else f"{group}-{index}.pack"
        path = OUT_DIR / label
        size = write_tar(path, items)
        if size > CHUNK:
            raise SystemExit(f"Vẫn quá 25 MB: {path.name}")
        print(f"TAR {path.name} {size}")
        written.append(path)
    return written


def emit_raw(group: str, src: Path) -> list[Path]:
    parts: list[Path] = []
    with src.open("rb") as handle:
        index = 1
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            if src.stat().st_size <= CHUNK:
                name = f"{group}.pack"
            else:
                name = f"{group}.{index:02d}"
            path = OUT_DIR / name
            path.write_bytes(block)
            if path.stat().st_size > CHUNK:
                raise SystemExit(f"Phần quá 25 MB: {path.name}")
            print(f"RAW {path.name} {path.stat().st_size}")
            parts.append(path)
            index += 1
            if src.stat().st_size <= CHUNK:
                break
    return parts


def collect() -> dict[str, list[tuple[str, Path]]]:
    groups: dict[str, list[tuple[str, Path]]] = {}
    for path in SRC.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(SRC).as_posix()
        group = group_of(rel)
        if group is None:
            continue
        groups.setdefault(group, []).append((rel, path))
    for items in groups.values():
        items.sort(key=lambda item: item[0])
    return groups


def build() -> tuple[list[Path], dict[str, list[str]], dict[str, list[str]]]:
    if not (SRC / "excel-explorer.exe").exists():
        raise SystemExit(f"Chưa có bản đóng gói: {SRC}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.iterdir():
        if old.is_file():
            old.unlink()

    made: list[Path] = []
    raw_jobs: list[tuple[str, list[str]]] = []
    tar_names: list[str] = []
    group_files: dict[str, list[str]] = {}
    contained: dict[str, list[str]] = {}

    run_bytes = RUN_BAT.replace("\n", "\r\n").encode("utf-8")
    groups = collect()
    for group in GROUP_INFO:
        items = groups.get(group, [])
        raw_items = [(rel, path) for rel, path in items if path.stat().st_size > 8_000_000]
        small_items = [(rel, path) for rel, path in items if path.stat().st_size <= 8_000_000]
        sent: list[str] = []
        inside: list[str] = []

        for rel, path in raw_items:
            if small_items:
                label = group if len(raw_items) == 1 else f"{group}-{path.stem[:20]}"
                label = f"{label}-bin" if len(raw_items) == 1 else label
            else:
                label = group if len(raw_items) == 1 else f"{group}-{path.stem[:20]}"
            parts = emit_raw(label, path)
            # Một nhóm có nhiều file lớn thì tên theo stem sẽ khó đọc. Hiện mỗi nhóm chỉ có một file lớn.
            dest = "excel-explorer/" + stored_rel(rel)
            raw_jobs.append((dest, [part.name for part in parts]))
            sent.extend(part.name for part in parts)
            inside.append(stored_rel(rel))
            made.extend(parts)

        if small_items or group == "runtime":
            pairs = [(path, f"excel-explorer/{stored_rel(rel)}") for rel, path in small_items]
            if group == "runtime":
                run_file = OUT_DIR / "_run.bat.src"
                run_file.write_bytes(run_bytes)
                pairs.append((run_file, "excel-explorer/run.bat"))
                inside.append("run.bat")
            if pairs:
                archives = emit_tars(group, pairs)
                for archive in archives:
                    tar_names.append(archive.name)
                    sent.append(archive.name)
                    made.append(archive)
                inside.extend(stored_rel(rel) for rel, _ in small_items)
            if group == "runtime":
                run_file.unlink()

        group_files[group] = sent
        contained[group] = inside

    blocked = [path.name for path in made if path.name.lower().endswith((".exe", ".zip"))]
    if blocked:
        raise SystemExit("Tên file gửi vẫn bị chặn: " + ", ".join(blocked))
    oversized = [path.name for path in made if path.stat().st_size > CHUNK]
    if oversized:
        raise SystemExit("Còn file quá 25 MB: " + ", ".join(oversized))

    write_mo_bat(raw_jobs, tar_names)
    write_guide()
    write_notes(group_files, contained, made)
    verify(groups, run_bytes, raw_jobs, [OUT_DIR / name for name in tar_names])
    print(f"OK {len(made)} files")
    return made, group_files, contained


def write_mo_bat(raw_jobs: list[tuple[str, list[str]]], tar_names: list[str]) -> None:
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        'cd /d "%~dp0"',
        "title Excel Explorer",
        "",
        "where tar >nul 2>&1",
        "if errorlevel 1 (",
        "    echo May nay khong co lenh tar. Can Windows 10 tro len.",
        "    pause",
        "    exit /b 1",
        ")",
        "",
        "echo Dang giai nen...",
    ]
    dirs: set[str] = set()
    for dest, _parts in raw_jobs:
        parent = str(Path(dest).parent).replace("/", "\\")
        if parent and parent != ".":
            dirs.add(parent)
    for folder in sorted(dirs):
        lines.append(f'if not exist "%~dp0{folder}" mkdir "%~dp0{folder}"')
    lines.append("")
    for name in tar_names:
        lines.append(f'tar -xf "%~dp0{name}" -C "%~dp0"')
        lines.append("if errorlevel 1 (")
        lines.append(f"    echo Giai nen {name} that bai.")
        lines.append("    pause")
        lines.append("    exit /b 1")
        lines.append(")")
    lines.append("")
    for dest, parts in raw_jobs:
        joined = "+".join(f'"%~dp0{part}"' for part in parts)
        bat_dest = dest.replace("/", "\\")
        lines.append(f'copy /b /y {joined} "%~dp0{bat_dest}" >nul')
        lines.append("if errorlevel 1 (")
        lines.append(f"    echo Ghep {dest} that bai.")
        lines.append("    pause")
        lines.append("    exit /b 1")
        lines.append(")")
    lines.extend(
        [
            "",
            'cd /d "%~dp0excel-explorer"',
            "call run.bat",
            "",
        ]
    )
    (OUT_DIR / "mo.bat").write_bytes(("\r\n".join(lines)).encode("ascii"))


def write_guide() -> None:
    text = """Gui ca thu muc nay, tru khi duoc bao chi gui mot vai file.
Moi file deu nho hon 25 MB. Khong co file .exe va khong co file .zip.

May kia: giu tat ca file trong cung mot thu muc, roi double-click mo.bat.
Lan sau neu chi nhan file thay the: copy de len file cung ten, roi chay lai mo.bat.
Khong can cai Python.
"""
    (OUT_DIR / "HUONG-DAN.txt").write_text(text, encoding="utf-8")


def write_notes(group_files: dict[str, list[str]], contained: dict[str, list[str]], made: list[Path]) -> None:
    NOTE_DIR.mkdir(parents=True, exist_ok=True)
    for old in NOTE_DIR.glob("*.md"):
        if old.name != "LAN-GUI.md":
            old.unlink()

    sizes = {path.name: path.stat().st_size for path in made}
    hashes = []
    for path in sorted(made, key=lambda item: item.name):
        hashes.append(f"{sha256_file(path)}  {path.name}")
    (NOTE_DIR / "SHA256.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")

    lines = [
        "# Note gói chuyển máy",
        "",
        "Sửa code trên máy này. Máy kia chỉ chạy app, không sửa code từ các file này.",
        "",
        "Lần đầu: gửi cả thư mục `chuyen-may`. Không gửi thư mục `note`.",
        "",
        "Lần sau: chỉ gửi file mình nói. Máy kia copy đè file cùng tên, giữ nguyên file còn lại, rồi double-click `mo.bat`.",
        "",
        "`SHA256.txt` là dấu vân của từng file. Lần đóng gói sau so với file này để biết phần nào đổi.",
        "",
        "## Gửi kèm, không phải pack",
        "",
        "- `mo.bat`: nút mở trên máy kia. Chỉ gửi lại khi cách giải nén hoặc cách mở app đổi.",
        "- `HUONG-DAN.txt`: vài dòng hướng dẫn. Chỉ gửi lại khi lời hướng dẫn đổi.",
        "",
        "## Từng nhóm",
        "",
        "| Nhóm | File gửi | Khi nào thay |",
        "|---|---|---|",
    ]
    for group, (title, _what, when) in GROUP_INFO.items():
        files = ", ".join(f"`{name}`" for name in group_files.get(group, [])) or "(không có file)"
        lines.append(f"| {title} | {files} | {when} |")
    lines.extend(["", "Chi tiết từng nhóm nằm ở file cùng tên trong thư mục này.", ""])
    (NOTE_DIR / "00-DOC-TRUOC.md").write_text("\n".join(lines), encoding="utf-8")

    for group, (title, what, when) in GROUP_INFO.items():
        body = [
            f"# {title}",
            "",
            what,
            "",
            f"Thay khi: {when}",
            "",
            "File gửi:",
            "",
        ]
        for name in group_files.get(group, []):
            body.append(f"- `{name}` — {sizes.get(name, 0) / 1_000_000:.1f} MB")
        body.extend(["", "Bên trong:", ""])
        shown = contained.get(group, [])
        for rel in shown[:40]:
            body.append(f"- `{rel}`")
        if len(shown) > 40:
            body.append(f"- … và {len(shown) - 40} file khác")
        body.append("")
        (NOTE_DIR / f"{group}.md").write_text("\n".join(body), encoding="utf-8")

    history = NOTE_DIR / "LAN-GUI.md"
    if not history.exists():
        history.write_text(
            "# Lần gửi\n\n## 2026-11-17 — lần đầu\n\nGửi toàn bộ thư mục `chuyen-may`. Chưa có file nào trên máy kia.\n",
            encoding="utf-8",
        )


def verify(
    groups: dict[str, list[tuple[str, Path]]],
    run_bytes: bytes,
    raw_jobs: list[tuple[str, list[str]]],
    tar_paths: list[Path],
) -> None:
    """Đọc lại các gói và so từng file với bản dist."""
    expected: dict[str, Path | bytes] = {}
    for items in groups.values():
        for rel, path in items:
            expected[f"excel-explorer/{stored_rel(rel)}"] = path
    expected["excel-explorer/run.bat"] = run_bytes

    for path in tar_paths:
        with tarfile.open(path, "r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                data = tar.extractfile(member).read()
                src = expected.pop(member.name, None)
                if src is None:
                    raise SystemExit(f"File lạ trong {path.name}: {member.name}")
                want = src if isinstance(src, bytes) else sha256_file(src)
                got = sha256_bytes(data) if not isinstance(src, bytes) else data
                if isinstance(src, bytes):
                    if got != want:
                        raise SystemExit(f"Lệch nội dung {member.name}")
                elif got != want:
                    raise SystemExit(f"Lệch nội dung {member.name}")

    for dest, parts in raw_jobs:
        src = expected.pop(dest, None)
        if not isinstance(src, Path):
            raise SystemExit(f"Không đối chiếu được {dest}")
        digest = hashlib.sha256()
        for name in parts:
            with (OUT_DIR / name).open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        if digest.hexdigest() != sha256_file(src):
            raise SystemExit(f"Lệch file raw {dest}")

    if expected:
        missing = ", ".join(sorted(expected)[:8])
        raise SystemExit(f"Còn file chưa được đóng: {missing}")
    print("VERIFY ok")


def _is_tar(path: Path) -> bool:
    with path.open("rb") as handle:
        magic = handle.read(2)
    return magic == b"\x1f\x8b"


def main() -> None:
    build()


if __name__ == "__main__":
    main()
