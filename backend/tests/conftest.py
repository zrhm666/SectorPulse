from pathlib import Path

import pytest

from backend.tests.postgres_isolation import isolate_configured_postgres_url


@pytest.fixture(autouse=True, scope="session")
def _no_business_database() -> None:
    """Applied to every test, not only `postgres`-marked ones.

    Several contract tests read `SECTOR_PULSE_DATABASE_URL` without carrying the
    marker, so a marker-scoped guard would leave them exposed to the business
    connection once `.env` reaches the process environment.
    """
    isolate_configured_postgres_url()


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
    parser.addoption(
        "--run-live-rag",
        action="store_true",
        default=False,
        help="run tests that call real embedding/reranker/NLI providers on a fixture corpus",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_live = config.getoption("--run-live") and Path(".live-data-consent").is_file()
    run_live_llm = config.getoption("--run-live-llm") and Path(".live-llm-consent").is_file()
    # `live_rag` 单独一档，因为它花的是 embedding / reranker / NLI 的钱，与行情和对话模型都
    # 不是同一笔账；共用一份同意书会让"我同意联网取行情"顺手变成"我同意按 token 付费"。
    run_live_rag = config.getoption("--run-live-rag") and Path(".live-rag-consent").is_file()
    for item in items:
        # 三档各自看自己的 marker，**不用** `in item.keywords`：`keywords` 里除了 marker 名
        # 还有目录名与节点名，而 `backend/tests/live/` 这个目录本身就叫 `live`。于是"带
        # `live_rag` 标记"的用例会被行情那一档拦下，报出的原因还是行情那份同意书——Task 20
        # 实测：整份 RAG 冒烟套件在离线运行里被报成 "requires --run-live and
        # .live-data-consent"，即使它一次行情都不取。`get_closest_marker` 是精确匹配，
        # 路径与用例名都不会误伤，`live_llm` 也不必再写一条"排除自己"的条件。
        if item.get_closest_marker("live") is not None and not run_live:
            item.add_marker(pytest.mark.skip(reason="requires --run-live and .live-data-consent"))
        if item.get_closest_marker("live_llm") is not None and not run_live_llm:
            item.add_marker(
                pytest.mark.skip(reason="requires --run-live-llm and .live-llm-consent")
            )
        if item.get_closest_marker("live_rag") is not None and not run_live_rag:
            item.add_marker(
                pytest.mark.skip(reason="requires --run-live-rag and .live-rag-consent")
            )
