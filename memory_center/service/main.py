"""Foreground service entry point; Uvicorn owns signals and shutdown."""
import argparse
import os
import socket
from pathlib import Path

import uvicorn

from memory_center.service.app import create_service_app
from memory_center.service.config import ServiceConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Memory Center 5.0 独立服务")
    parser.add_argument("--host", default=os.environ.get("MEMORY_CENTER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=os.environ.get("MEMORY_CENTER_PORT", "8765"))
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get(
        "MEMORY_CENTER_DATA_DIR", str(ServiceConfig.default().data_dir))))
    parser.add_argument("--allowed-host", action="append", help="附加允许的 HTTP Host（例如 memory.local:*）")
    args = parser.parse_args()
    try:
        config = ServiceConfig(args.data_dir.expanduser().resolve(), args.host, args.port,
                               ServiceConfig.default().allowed_hosts + tuple(args.allowed_host or ()),
                               os.environ.get("MEMORY_CENTER_DATABASE_URL", ""))
    except ValueError as exc:
        parser.error(str(exc))
    try:
        addresses = socket.getaddrinfo(config.host, config.port, type=socket.SOCK_STREAM)
        family, socktype, proto, _, address = addresses[0]
        with socket.socket(family, socktype, proto) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(address)
            listener.listen(128)
            server = uvicorn.Server(uvicorn.Config(
                create_service_app(config), host=config.host, port=config.port,
                workers=1, timeout_graceful_shutdown=10,
            ))
            server.run(sockets=[listener])
            return 0 if server.started else 1
    except OSError as exc:
        parser.exit(1, f"服务启动失败：监听地址不可用或端口已被占用（{exc.strerror}）\n")


if __name__ == "__main__":
    raise SystemExit(main())
