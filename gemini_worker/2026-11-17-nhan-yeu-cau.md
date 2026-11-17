# Nhận yêu cầu — Excel/CSV Explorer

Ngày: 2026-11-17

## Đã làm

- Đọc spec đầy đủ: web app localhost, 1 user, Python + SQLite, đóng gói PyInstaller `--onedir`, chạy offline.
- Workspace `visualize_webpro_duyloc` đang trống, chưa có source.
- Tạo folder `gemini_worker` để ghi log sau mỗi task đáng lưu.
- Chưa viết code app. Spec yêu cầu trả lời 4 câu (mục 11) trước Phase 1.

## Ràng buộc đã nắm

- Nền tảng: Python + SQLite. DuckDB optional, khuyến nghị bản full.
- Máy đích: giải nén → double-click → browser. Không cài Python, không internet, không admin.
- Data runtime nằm cạnh exe (`get_data_dir`), không nhét vào `_MEIPASS`.
- Frontend: HTML + HTMX + Alpine.js + Tailwind, vendor local để offline.
- Làm theo phase 1 → 4, dừng sau mỗi phase để test.

## Đang chờ

1. OS máy đích
2. Bản full (DuckDB + Polars) hay lite (pandas)
3. Icon app
4. Đa ngôn ngữ Việt/Anh
