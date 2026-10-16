# 包入口：支持 `python -m mt5connector` 与 console script `mt5connector-server`。
# 与原 server.py 行为一致——单进程 uvicorn 常驻，默认 127.0.0.1:8090。

from __future__ import annotations

import uvicorn

from .config import load_settings
from .main import create_app


def main() -> None:
    """启动连接器 HTTP 服务（端口/终端路径等全部来自环境变量，见 config.py）。"""
    settings = load_settings()
    app = create_app(settings)
    uvicorn.run(app, host="127.0.0.1", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
