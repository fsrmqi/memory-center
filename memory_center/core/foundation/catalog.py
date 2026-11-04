"""项目目录错误；与 HTTP 传输解耦。"""


class CatalogError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
