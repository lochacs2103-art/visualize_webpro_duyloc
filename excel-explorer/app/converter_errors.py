"""Lỗi convert mà người dùng có thể xử lý bằng cách chọn lại file hoặc dòng tiêu đề."""


class ConvertError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
