# Gói chuyển máy không dùng đuôi exe và zip

Ngày: 2026-11-17

Thư mục `chuyen-may` có `excel-explorer.pack` (tar.gz, khoảng 148 MB), `mo.bat`, `HUONG-DAN.txt`. Trong pack không có tên file kết thúc bằng .exe hoặc .zip. Ba file bị đổi tên: `excel-explorer.app`, `vc_redist.x64.app`, `_internal/base_library.dat`. `mo.bat` giải nén bằng tar của Windows rồi `run.bat` copy lại đúng tên trước khi mở app.

Đã giải nén thử bằng tar của Windows. Kích thước file exe và base_library.zip sau khi phục hồi khớp bản dist.

Đã cắt `excel-explorer.pack` thành 7 phần, mỗi phần tối đa 24.000.000 byte. `mo.bat` ghép lại bằng `copy /b` rồi giải nén. Hash sau khi ghép khớp file gốc.

Sau đó tách lại theo nội dung, vì 7 khúc byte không thể thay riêng. Thư mục `note` ghi từng nhóm. `chuyen-may` giờ có `app.pack`, `static.pack`, `templates.pack`, `runtime.pack`, và các phần polars, duckdb, pandas, numpy, vc. Mỗi file không quá 24 MB. Đã đọc lại và đối chiếu hash với bản dist.
