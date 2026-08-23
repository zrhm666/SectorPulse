"""本地 Web 管理台启动入口。"""

from pathlib import Path

import uvicorn

from sector_pulse.web.app import create_app


def build_log_config() -> dict[str, object]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(asctime)s [%(levelprefix)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "use_colors": None,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": (
                    "%(asctime)s [%(levelprefix)s] %(client_addr)s - "
                    "\"%(request_line)s\" %(status_code)s"
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "use_colors": None,
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "class": "logging.StreamHandler",
                "formatter": "access",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }


def main() -> None:
    """启动单用户本机服务，默认只监听回环地址。"""
    uvicorn.run(
        create_app(static_dir=Path("web/dist")),
        host="127.0.0.1",
        port=8000,
        log_config=build_log_config(),
    )


if __name__ == "__main__":
    main()
