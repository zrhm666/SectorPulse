from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests that access live market providers",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live") and Path(".live-data-consent").is_file():
        return
    marker = pytest.mark.skip(reason="requires --run-live and .live-data-consent")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(marker)
