"""Explicit service configuration; never discovers a legacy workspace."""
import ipaddress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServiceConfig:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "[::1]", "127.0.0.1:*", "localhost:*", "[::1]:*")

    database_url: str = ""
    auth_mode: str = "local"
    container_local: bool = False

    def __post_init__(self):
        if not 1 <= self.port <= 65535:
            raise ValueError("端口必须介于 1 和 65535 之间")
        if not self.host:
            raise ValueError("监听地址不能为空")
        if self.auth_mode not in {"local", "token"}:
            raise ValueError("认证模式需为 local 或 token")
        if self.auth_mode == "local" and not self.container_local:
            try:
                loopback = self.host == "localhost" or ipaddress.ip_address(self.host).is_loopback
            except ValueError:
                loopback = False
            if not loopback:
                raise ValueError("免认证模式只允许监听本机；容器仅在宿主回环端口发布时使用 --container-local")

    @classmethod
    def default(cls):
        return cls(data_dir=Path.home() / ".memory-center" / "v5")
