"""Explicit service configuration; never discovers a legacy workspace."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServiceConfig:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "[::1]", "127.0.0.1:*", "localhost:*", "[::1]:*")

    database_url: str = ""

    def __post_init__(self):
        if not 1 <= self.port <= 65535:
            raise ValueError("端口必须介于 1 和 65535 之间")
        if not self.host:
            raise ValueError("监听地址不能为空")

    @classmethod
    def default(cls):
        return cls(data_dir=Path.home() / ".memory-center" / "v5")
