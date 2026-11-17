"""Tạo 2 file Excel văn phòng mẫu để nạp thử trên web."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

OUT = Path(__file__).resolve().parent.parent / "samples"
HEADER_FILL = PatternFill("solid", fgColor="B45309")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14)
THIN = Border(
    left=Side(style="thin", color="D6D3D1"),
    right=Side(style="thin", color="D6D3D1"),
    top=Side(style="thin", color="D6D3D1"),
    bottom=Side(style="thin", color="D6D3D1"),
)


def style_header(ws, row: int, width: int) -> None:
    for col in range(1, width + 1):
        cell = ws.cell(row, col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    ws.auto_filter.ref = f"A{row}:{get_column_letter(width)}{ws.max_row}"
    ws.freeze_panes = f"A{row + 1}"
    for col in range(1, width + 1):
        letter = get_column_letter(col)
        ws.column_dimensions[letter].width = 18


def chi_phi() -> None:
    """Dòng tiêu đề ở dòng 1. Nạp ngay được."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Chi phí"
    headers = [
        "Ngày chi",
        "Số chứng từ",
        "Hạng mục",
        "Phòng ban",
        "Người đề nghị",
        "Nhà cung cấp",
        "Số tiền",
        "VAT",
        "Hình thức",
        "Trạng thái",
        "Ghi chú",
    ]
    sheet.append(headers)
    departments = ["Hành chính", "Kế toán", "Kinh doanh", "Nhân sự", "IT"]
    people = ["Nguyễn Thu Hà", "Trần Minh Quân", "Lê Thị Mai", "Phạm Đức Anh", "Võ Ngọc Lan"]
    vendors = ["Văn phòng phẩm An Bình", "Điện lực Quận 1", "Grab for Business", "FPT Telecom", "Công ty CP In Ấn Hoa Sen"]
    items = ["Văn phòng phẩm", "Điện nước", "Taxi công tác", "Internet", "In ấn tài liệu", "Sửa máy lạnh", "Tiếp khách"]
    states = ["Đã thanh toán", "Chờ duyệt", "Đã duyệt", "Từ chối"]
    start = date(2026, 11, 2)
    for index in range(1, 43):
        amount = 350_000 + (index * 87_500) % 12_000_000
        sheet.append(
            [
                start + timedelta(days=index % 26),
                f"PC26-11-{index:03d}",
                items[index % len(items)],
                departments[index % len(departments)],
                people[index % len(people)],
                vendors[index % len(vendors)],
                amount,
                round(amount * 0.1) if index % 3 else 0,
                "Chuyển khoản" if index % 2 else "Tiền mặt",
                states[index % len(states)],
                "" if index % 5 else "Xuất hóa đơn đỏ, lưu hồ sơ quyết toán quý 4",
            ]
        )
    for row in sheet.iter_rows(min_row=2, min_col=1, max_col=1):
        row[0].number_format = "DD/MM/YYYY"
    for row in sheet.iter_rows(min_row=2, min_col=7, max_col=8):
        row[0].number_format = "#,##0"
        row[1].number_format = "#,##0"
    style_header(sheet, 1, len(headers))
    sheet.column_dimensions["K"].width = 42

    summary = book.create_sheet("Theo phòng ban")
    summary.append(["Phòng ban", "Số phiếu", "Tổng tiền", "Tổng VAT"])
    for name in departments:
        summary.append([name, 8 + len(name) % 4, 18_500_000 + len(name) * 250_000, 1_850_000])
    for row in summary.iter_rows(min_row=2, min_col=3, max_col=4):
        row[0].number_format = "#,##0"
        row[1].number_format = "#,##0"
    style_header(summary, 1, 4)
    book.save(OUT / "chi_phi_van_phong.xlsx")


def cong_van() -> None:
    """Ba dòng tiêu đề phía trên. Khi nạp, chọn dòng tiêu đề số 4 cho cả hai sheet."""
    book = Workbook()
    incoming = book.active
    incoming.title = "Công văn đến"
    _preamble(incoming, "SỔ CÔNG VĂN ĐẾN", "Tháng 11/2026")
    incoming.append(["Số công văn", "Ngày nhận", "Nơi gửi", "Trích yếu", "Độ khẩn", "Hạn xử lý", "Người xử lý", "Tình trạng"])
    senders = ["UBND Quận 1", "Cục Thuế TP.HCM", "Sở Kế hoạch và Đầu tư", "Ngân hàng Vietcombank", "Công ty TNHH Bắc Nam"]
    topics = [
        "Mời họp giao ban tháng 11",
        "Thông báo quyết toán thuế GTGT",
        "Nhắc gia hạn giấy phép kinh doanh",
        "Xác nhận số dư tài khoản",
        "Đề nghị đối soát công nợ quý 3",
        "Mời tham gia tập huấn an toàn lao động",
    ]
    urgency = ["Thường", "Khẩn", "Hỏa tốc"]
    owners = ["Phạm Thu Trang", "Đỗ Quang Huy", "Ngô Thị Hồng", "Bùi Văn Khôi"]
    status = ["Đã xử lý", "Đang xử lý", "Chờ phân công", "Quá hạn"]
    for index in range(1, 31):
        received = date(2026, 11, 1) + timedelta(days=index % 20)
        incoming.append(
            [
                f"{index:03d}/CV-Đ",
                received,
                senders[index % len(senders)],
                topics[index % len(topics)],
                urgency[index % len(urgency)],
                received + timedelta(days=3 + index % 7),
                owners[index % len(owners)],
                status[index % len(status)],
            ]
        )
    _dates(incoming, 5, [2, 6])
    style_header(incoming, 4, 8)
    incoming.column_dimensions["D"].width = 42

    outgoing = book.create_sheet("Công văn đi")
    _preamble(outgoing, "SỔ CÔNG VĂN ĐI", "Tháng 11/2026")
    outgoing.append(["Số công văn", "Ngày đi", "Nơi nhận", "Trích yếu", "Người ký", "Hình thức", "Tình trạng"])
    for index in range(1, 19):
        sent = date(2026, 11, 3) + timedelta(days=index)
        outgoing.append(
            [
                f"{index:03d}/CV-ML",
                sent,
                senders[(index + 1) % len(senders)],
                topics[(index + 2) % len(topics)],
                "Giám đốc Lê Hoàng Nam" if index % 2 else "Kế toán trưởng Trần Kim Oanh",
                "Bản giấy" if index % 3 else "Email",
                "Đã phát hành" if index % 4 else "Đang soạn",
            ]
        )
    _dates(outgoing, 5, [2])
    style_header(outgoing, 4, 7)
    outgoing.column_dimensions["D"].width = 42
    book.save(OUT / "cong_van_thang_11.xlsx")


def _preamble(ws, title: str, period: str) -> None:
    ws.append(["CÔNG TY TNHH MINH LỘC"])
    ws.append([title])
    ws.append([period])
    ws["A1"].font = TITLE_FONT
    ws["A2"].font = Font(bold=True, size=12)


def _dates(ws, start_row: int, columns: list[int]) -> None:
    for col in columns:
        for cell in ws.iter_rows(min_row=start_row, min_col=col, max_col=col):
            cell[0].number_format = "DD/MM/YYYY"


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    chi_phi()
    cong_van()
    print(OUT / "chi_phi_van_phong.xlsx")
    print(OUT / "cong_van_thang_11.xlsx")
