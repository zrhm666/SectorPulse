"""本地 Web 管理台启动入口。"""

from pathlib import Path

import uvicorn

from sector_pulse.web.app import create_app


def main() -> None:
    """启动单用户本机服务，默认只监听回环地址。"""
    uvicorn.run(
        create_app(static_dir=Path("web/dist")),
        host="127.0.0.1",
        port=8000,
    )


if __name__ == "__main__":
    main()
