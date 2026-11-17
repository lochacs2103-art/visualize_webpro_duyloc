Excel Explorer — bản đóng gói

1. Giải nén cả thư mục.
2. Chạy run.bat. Lần đầu, nếu thiếu Visual C++ Runtime và có vc_redist.x64.exe, script sẽ cài im lặng.
3. Trình duyệt mở http://127.0.0.1:8000
4. Dữ liệu nằm trong thư mục data cạnh file exe. Tắt app rồi mở lại thì dữ liệu còn.
5. Nếu DuckDB hoặc Polars không chạy được, app ghi cảnh báo vào logs/app.log và vẫn mở (chậm hơn).

vc_redist.x64.exe tải từ Microsoft:
https://aka.ms/vs/17/release/vc_redist.x64.exe
Đặt cạnh run.bat trước khi gửi máy khác. Không cần internet trên máy đích.
