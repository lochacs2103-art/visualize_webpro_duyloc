# Nút run.bat ở gốc project

Ngày: 2026-11-17

`run.bat` nằm ở gốc thư mục. Máy khác không cần Python. Script mở `excel-explorer\dist\excel-explorer\excel-explorer.exe` và trỏ dữ liệu về `excel-explorer\data` bằng `EXCEL_EXPLORER_HOME`.

Đã build lại exe để biến môi trường này có hiệu lực. Đã chạy nút: `/health` ok, log ghi đúng thư mục data, trang chủ và file chi phí mở được.

Máy đích phải có cả thư mục `excel-explorer\dist\excel-explorer` (exe, `_internal`, `vc_redist.x64.exe`), không chỉ mỗi file `run.bat`.
