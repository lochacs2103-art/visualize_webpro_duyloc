"""Ba file customer, order, transaction dùng chung khóa để test mapping."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

OUT = Path(__file__).resolve().parent.parent / "samples"
HEADER_FILL = PatternFill("solid", fgColor="166534")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def save(name: str, sheet_name: str, headers: list[str], rows: list[list], date_cols: list[int], money_cols: list[int]) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = sheet_name
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    for col in range(1, len(headers) + 1):
        cell = sheet.cell(1, col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        sheet.column_dimensions[get_column_letter(col)].width = 22
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{sheet.max_row}"
    for col in date_cols:
        for cell in sheet.iter_rows(min_row=2, min_col=col, max_col=col):
            cell[0].number_format = "DD/MM/YYYY"
    for col in money_cols:
        for cell in sheet.iter_rows(min_row=2, min_col=col, max_col=col):
            cell[0].number_format = "#,##0"
    book.save(OUT / name)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    save(
        "customer.xlsx",
        "Khach hang",
        ["Ma_KH", "Ten_khach", "Thanh_pho", "Nhom"],
        [
            ["KH01", "Công ty An Phát", "Hà Nội", "Doanh nghiệp"],
            ["KH02", "Cửa hàng Minh Khai", "Đà Nẵng", "Cá nhân"],
            ["KH03", "Công ty Bình Minh", "TP.HCM", "Doanh nghiệp"],
            ["KH04", "Nhà thuốc Hoa Sen", "Cần Thơ", "Cá nhân"],
            ["KH05", "Công ty Delta", "Hải Phòng", "Doanh nghiệp"],
        ],
        [],
        [],
    )
    save(
        "order.xlsx",
        "Don hang",
        ["Ma_don", "CustomerID", "Ngay_dat", "Trang_thai"],
        [
            ["DH001", "KH01", date(2026, 10, 2), "Đã giao"],
            ["DH002", "KH01", date(2026, 10, 15), "Đã giao"],
            ["DH003", "KH02", date(2026, 10, 20), "Đang giao"],
            ["DH004", "KH03", date(2026, 11, 1), "Đã giao"],
            ["DH005", "KH03", date(2026, 11, 8), "Hủy"],
            ["DH006", "KH04", date(2026, 11, 12), "Đã giao"],
            ["DH007", "KH05", date(2026, 11, 18), "Đã giao"],
            ["DH008", "KH02", date(2026, 11, 22), "Chờ thanh toán"],
        ],
        [3],
        [],
    )
    save(
        "transaction.xlsx",
        "Giao dich",
        ["Ma_GD", "OrderID", "Ma_KH", "Ngay_thanh_toan", "So_tien", "Hinh_thuc"],
        [
            ["GD01", "DH001", "KH01", date(2026, 10, 3), 2_500_000, "Chuyển khoản"],
            ["GD02", "DH001", "KH01", date(2026, 10, 5), 1_500_000, "Chuyển khoản"],
            ["GD03", "DH002", "KH01", date(2026, 10, 16), 3_200_000, "Tiền mặt"],
            ["GD04", "DH003", "KH02", date(2026, 10, 21), 800_000, "Chuyển khoản"],
            ["GD05", "DH004", "KH03", date(2026, 11, 2), 4_100_000, "Chuyển khoản"],
            ["GD06", "DH004", "KH03", date(2026, 11, 4), 900_000, "Thẻ"],
            ["GD07", "DH006", "KH04", date(2026, 11, 13), 1_750_000, "Chuyển khoản"],
            ["GD08", "DH007", "KH05", date(2026, 11, 19), 5_600_000, "Chuyển khoản"],
            ["GD09", "DH008", "KH02", date(2026, 11, 23), 450_000, "Tiền mặt"],
        ],
        [4],
        [5],
    )
    print(OUT / "customer.xlsx")
    print(OUT / "order.xlsx")
    print(OUT / "transaction.xlsx")


if __name__ == "__main__":
    main()
