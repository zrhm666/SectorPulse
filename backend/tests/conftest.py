from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests that access live market providers",
    )
    parser.addoption(
        "--run-live-llm",
        action="store_true",
        default=False,
        help="run tests that access a configured live LLM provider",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_live = config.getoption("--run-live") and Path(".live-data-consent").is_file()
    run_live_llm = config.getoption("--run-live-llm") and Path(".live-llm-consent").is_file()
    for item in items:
        if "live" in item.keywords and "live_llm" not in item.keywords and not run_live:
            item.add_marker(pytest.mark.skip(reason="requires --run-live and .live-data-consent"))
        if "live_llm" in item.keywords and not run_live_llm:
            item.add_marker(
                pytest.mark.skip(reason="requires --run-live-llm and .live-llm-consent")
            )
