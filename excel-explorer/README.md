# Excel Explorer — Phase 1

Ứng dụng localhost để nạp Excel, giữ file gốc, ghi CSV theo ngày và xem bảng theo trang.
Giai đoạn này là khung chạy được. Bộ lọc, SQL, virtual scroll, export và đóng gói nằm ở các phase sau.

## Chạy trên Windows

```bat
cd excel-explorer
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Mở http://127.0.0.1:8000. Thư mục dữ liệu nằm cạnh app: `excel-explorer\data`.

Đặt `EXCEL_EXPLORER_NO_BROWSER=1` nếu không muốn tự mở trình duyệt.

## Phase 1 có gì

- Nạp `.xlsx` / `.xls`, xem 10 dòng đầu và chọn dòng tiêu đề
- `.xlsx` ghi CSV theo từng dòng (openpyxl read_only). `.xls` đi qua pandas
- CSV UTF-8-SIG, lưu `data/csv/YYYY-MM-DD/`
- Trùng tên trong cùng ngày thì thêm `_HHMMSS`
- Nhiều sheet: mỗi sheet một file, tên dạng `tên — sheet`
- Cây thư viện theo ngày, rê chuột để xem 5 dòng
- Bảng 200 dòng/trang, qua lại bằng URL `?offset=`
- Giao diện tiếng Việt / English, sáng / tối (lưu trong trình duyệt)
- `GET /health`

## Chưa làm trong phase này

Tiến trình nền (SSE), DuckDB filter, SQL editor, virtual scroll, export, parquet, theo dõi thư mục, profiling, schema diff, trùng dòng, join, saved view, ghim cột, conditional formatting, phím tắt, lịch, đóng gói exe.

## Giới hạn cần biết khi thử

- Cùng một dòng tiêu đề cho mọi sheet của file.
- Ô công thức lấy giá trị Excel đã lưu sẵn. File chưa được Excel tính thì ô đó có thể trống.
- Cột phía sau một tiêu đề bị cắt (ô tiêu đề cuối trống) sẽ không vào CSV.
- Icon file exe sẽ gắn ở Phase 4, khi có file `.ico`.
