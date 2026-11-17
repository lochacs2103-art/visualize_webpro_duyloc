# excel-explorer.spec
# Build: pyinstaller --noconfirm excel-explorer.spec
# upx tắt để tránh antivirus chặn. console bật để còn log khi máy đích lỗi.
from PyInstaller.utils.hooks import collect_all

datas = [
    ("templates", "templates"),
    ("static", "static"),
]
binaries = []
hiddenimports = []

for pkg in ("polars", "duckdb", "pandas", "openpyxl", "fastapi", "uvicorn", "watchdog", "anyio", "pydantic"):
    try:
        bundled, binary, hidden = collect_all(pkg)
        datas += bundled
        binaries += binary
        hiddenimports += hidden
    except Exception:
        pass

a = Analysis(
    ["main.py"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "test", "unittest", "pytest", "IPython", "jupyter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="excel-explorer",
    console=True,
    icon="static/favicon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="excel-explorer",
)
