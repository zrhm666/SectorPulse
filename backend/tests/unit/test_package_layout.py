"""Guard the approved package boundaries during backend reorganization."""

import ast
import importlib
import socket
from pathlib import Path

import pytest
import sector_pulse

ROOT = Path(sector_pulse.__file__).parent


def test_application_modules_are_grouped() -> None:
    assert {p.name for p in (ROOT / "application").glob("*.py")} <= {
        "__init__.py"
    }


def test_domain_root_contains_only_shared_contracts() -> None:
    assert {p.name for p in (ROOT / "domain").glob("*.py")} == {
        "__init__.py", "provider.py", "llm.py"
    }


def test_web_modules_have_explicit_responsibilities() -> None:
    assert {p.name for p in (ROOT / "web").glob("*.py")} == {
        "__init__.py", "app.py", "server.py", "dependencies.py", "errors.py"
    }


def test_storage_root_contains_only_shared_infrastructure() -> None:
    assert {p.name for p in (ROOT / "storage").glob("*.py")} == {
        "__init__.py", "database_config.py", "database_runtime.py",
        "runtime_bundle.py",
    }


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
def test_storage_dialect_root_is_small(dialect: str) -> None:
    assert {p.name for p in (ROOT / "storage" / dialect).glob("*.py")} == {
        "__init__.py", "database.py", "operations_query.py"
    }


# Modules that exist only for PostgreSQL by design. RAG 的权威仓库（资料、版本、摄取任务、
# 索引代次）只有 PostgreSQL 一份：SQLite 上的那些表是给离线运行用的，没有对应实现。
#
# 已接纳证据的**读取端**是例外，两种方言都有：那两张证据表本来就由接纳服务经事务会话写进
# 当前方言的库里（规格 15.2），如果只有 PostgreSQL 能读回来，SQLite 运行就能接纳一批谁也
# 读不到的证据。
#
# JSON 列的读法（`research_library/json_columns.py`）也只有 PostgreSQL 一侧需要：psycopg 3
# 把 JSONB 直接解析成 Python 对象，而 SQLite 只给 TEXT，所以"要不要再解析一次"是个方言问题。
# SQLite 那一侧继续显式 `json.loads` 是对的，不需要一个同名的孪生模块——这个模块存在，正是
# 因为这个差异，而不是因为它被漏掉了。
POSTGRES_ONLY_MODULES = frozenset({
    Path("research_library/repository.py"),
    Path("research_library/json_columns.py"),
})


def test_storage_dialects_have_matching_business_modules() -> None:
    sqlite = ROOT / "storage" / "sqlite"
    postgres = ROOT / "storage" / "postgres"
    sqlite_modules = {p.relative_to(sqlite) for p in sqlite.rglob("*.py")}
    postgres_modules = {p.relative_to(postgres) for p in postgres.rglob("*.py")}
    # Every SQLite module must also exist for PostgreSQL; the reverse may only differ
    # where the difference is named above, so an unlisted divergence still fails.
    assert sqlite_modules <= postgres_modules
    assert postgres_modules - sqlite_modules == POSTGRES_ONLY_MODULES


def test_storage_protocols_have_business_owners() -> None:
    assert {p.stem for p in (ROOT / "storage" / "ports").glob("*.py")} == {
        "__init__", "market", "news", "runs", "tasks", "writing", "review",
        "evaluation", "operations", "research_library",
    }


def test_runs_and_review_routers_have_separate_modules() -> None:
    routers = ROOT / "web" / "routers"
    assert (routers / "runs.py").is_file()
    assert (routers / "review.py").is_file()
    assert not (routers / "runs_review.py").exists()


def test_reorganized_modules_import_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbid_connect(*args: object, **kwargs: object) -> None:
        pytest.fail("Importing a backend module must not connect to external services")

    monkeypatch.setattr(socket.socket, "connect", forbid_connect)
    for layer in ("domain", "application", "storage", "web"):
        for file in sorted((ROOT / layer).rglob("*.py")):
            relative = file.relative_to(ROOT).with_suffix("")
            parts = relative.parts[:-1] if file.name == "__init__.py" else relative.parts
            module = importlib.import_module("sector_pulse." + ".".join(parts))
            assert Path(module.__file__).resolve() == file.resolve()
    importlib.import_module("sector_pulse.cli")
    importlib.import_module("sector_pulse.web.server")


def test_domain_does_not_depend_on_application_storage_or_web() -> None:
    forbidden = (
        "sector_pulse.application", "sector_pulse.storage", "sector_pulse.web",
        "sector_pulse.infrastructure",
    )
    for file in (ROOT / "domain").rglob("*.py"):
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden), file
            elif isinstance(node, ast.Import):
                assert not any(alias.name.startswith(forbidden) for alias in node.names), file
