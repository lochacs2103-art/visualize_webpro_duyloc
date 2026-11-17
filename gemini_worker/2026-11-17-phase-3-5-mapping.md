# Phase 3.5 — mapping / union

Ngày: 2026-11-17

## Đã làm

- Tab Raw: upload nhiều Excel, chưa convert. Xem 10 dòng, nạp vào thư viện, hoặc đưa vào mapping.
- Project mapping: cột chuẩn, kéo/chọn cột nguồn, gợi ý tên gần giống, preview 100 dòng, chạy nền ra CSV trong thư viện.
- CSV nguồn được cache. File raw không đổi thì không convert lại.
- `run.bat`, `excel-explorer.spec` (onedir, không UPX), `dist-ship/README.txt`.
- SortableJS 1.15.6 nằm trong `static/vendor/sortablejs/`.

## Đã kiểm tra

- Hai file thử: ngày `2026-11-01` và `02/11/2026`, số `1.250,50` ra `1250.5`. UNION 2 dòng, 0 lỗi. Đã xóa dữ liệu thử.
- Trang `/raw` và `/mappings` mở được.

## Chưa làm

- Chưa build exe, chưa tải `vc_redist.x64.exe`, chưa thử máy Windows sạch.
- Chart, heatmap, pivot của Phase 3 vẫn chưa có.
