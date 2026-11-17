# Note gói chuyển máy

Sửa code trên máy này. Máy kia chỉ chạy app, không sửa code từ các file này.

Lần đầu: gửi cả thư mục `chuyen-may`. Không gửi thư mục `note`.

Lần sau: chỉ gửi file mình nói. Máy kia copy đè file cùng tên, giữ nguyên file còn lại, rồi double-click `mo.bat`.

`SHA256.txt` là dấu vân của từng file. Lần đóng gói sau so với file này để biết phần nào đổi.

## Gửi kèm, không phải pack

- `mo.bat`: nút mở trên máy kia. Chỉ gửi lại khi cách giải nén hoặc cách mở app đổi.
- `HUONG-DAN.txt`: vài dòng hướng dẫn. Chỉ gửi lại khi lời hướng dẫn đổi.

## Từng nhóm

| Nhóm | File gửi | Khi nào thay |
|---|---|---|
| Chương trình | `app.pack` | Sửa code Python trên máy này, build lại exe, rồi gửi file của nhóm này. |
| Giao diện | `static.pack` | Sửa file trong thư mục static. |
| Trang HTML | `templates.pack` | Sửa file HTML trong thư mục templates. |
| Visual C++ | `vc.01`, `vc.02` | Gần như không đổi. Chỉ gửi lại khi mình nói. |
| Polars | `polars.01`, `polars.02`, `polars.03`, `polars.04`, `polars.05`, `polars.06`, `polars.07` | Khi nâng thư viện Polars. |
| Polars Python | `polars-py.pack` | Khi nâng thư viện Polars. |
| DuckDB | `duckdb.01`, `duckdb.02` | Khi nâng DuckDB. |
| DuckDB Python | `duckdb-py.pack` | Khi nâng DuckDB. |
| Pandas | `pandas.pack` | Khi nâng pandas. |
| NumPy | `numpy-bin.pack`, `numpy.pack` | Khi nâng numpy. |
| Phần còn lại | `runtime.pack` | Khi nâng Python hoặc các thư viện nhỏ này. |

Chi tiết từng nhóm nằm ở file cùng tên trong thư mục này.
