# Phase 3 nhóm B — chart và màu ô

Ngày: 2026-11-17

Mapping không đổi. Trong bảng có nút Visualize (cột, đường, vùng, tròn, điểm) và Hiển thị màu.

Chart lấy dữ liệu đã lọc, gom bằng DuckDB. Lưu chart vào SQLite. Tải PNG bằng html2canvas. ECharts 5.5.1 và html2canvas 1.4.1 nằm trong static/vendor.

Đã thử file chi phí: Bar, X = Hạng mục, Y = Số tiền, Sum ra 7 cột. Lọc Taxi còn 1 cột, 12.337.500, 6 dòng. Bật màu thì Số tiền và VAT có thanh và nền. Đã lưu rồi xóa chart thử.

Chưa làm nhóm C: thông tin cột và pivot.

Cột tiền dạng chữ `1,100,000` trước đó không vào trục Y nên chart báo lỗi. Giờ cột nào phần lớn ô đọc được thành số thì được dùng làm trục Y. File tháng 12 vẽ được Tổng tiền, ví dụ Mua laptop = 15.000.000.
