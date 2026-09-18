"""三档真实访问的门禁，逐条验证"谁拦谁"。

这份文件测的是一个**已经出过错的地方**。原来的写法是 `"live" in item.keywords`，看起来
在问"这个用例带 live 标记吗"，实际上 `keywords` 里除了 marker 名还有节点名——而
`backend/tests/live/` 这个**目录**本身就叫 `live`。于是 Task 20 新加的那份 RAG 冒烟套件
（只带 `live_rag`）在离线运行里被行情那一档拦下，报出的原因还是 `.live-data-consent`：
原因指错了同意书，而"我同意联网取行情"与"我同意按 token 付费"是两笔账。
现在改成 `get_closest_marker` 精确匹配，这份文件就是这么钉住的。

替身只有两个：一个假的 item（记下被加上的 marker），一个假的 `Path`（决定哪几份同意书
"存在"）。都是为了让四组开关的组合可以在离线状态下全部走到——真实运行里"同意书存在"
这一档恰恰是最难复现的一档。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from backend.tests import conftest as tests_conftest

DATA_CONSENT = ".live-data-consent"
LLM_CONSENT = ".live-llm-consent"
RAG_CONSENT = ".live-rag-consent"

DATA_REASON = "requires --run-live and .live-data-consent"
LLM_REASON = "requires --run-live-llm and .live-llm-consent"
RAG_REASON = "requires --run-live-rag and .live-rag-consent"


@dataclass
class FakeItem:
    """一个只回答"我带哪些 marker"的用例。"""

    markers: frozenset[str]
    added: list[pytest.Mark] = field(default_factory=list)

    def get_closest_marker(self, name: str) -> object | None:
        return object() if name in self.markers else None

    def add_marker(self, marker: pytest.Mark) -> None:
        self.added.append(marker)

    @property
    def reasons(self) -> list[str]:
        return [str(marker.kwargs["reason"]) for marker in self.added]


class FakeConfig:
    def __init__(self, **options: bool) -> None:
        self._options = options

    def getoption(self, name: str) -> bool:
        return self._options.get(name, False)


def a_path_type_where(*present: str) -> type:
    """一个 `Path` 替身：只有点名的文件存在。同意书是真实文件，测试不该依赖它恰好不在。"""

    class _Path:
        def __init__(self, value: object) -> None:
            self._value = str(value)

        def is_file(self) -> bool:
            return self._value in present

    return _Path


def gate(
    monkeypatch: pytest.MonkeyPatch,
    items: list[FakeItem],
    *,
    present: tuple[str, ...] = (),
    **options: bool,
) -> list[FakeItem]:
    monkeypatch.setattr(tests_conftest, "Path", a_path_type_where(*present))
    tests_conftest.pytest_collection_modifyitems(  # type: ignore[arg-type]
        FakeConfig(**options), items  # type: ignore[arg-type]
    )
    return items


def test_a_rag_smoke_test_reports_only_its_own_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """这一条就是那个 bug：一份只带 `live_rag` 的用例曾经被报成"需要行情同意书"。"""
    item, = gate(
        monkeypatch,
        [FakeItem(frozenset({"live_rag"}))],
        **{"--run-live": True, "--run-live-llm": True, "--run-live-rag": True},
    )

    assert item.reasons == [RAG_REASON]


def test_rag_consent_alone_is_enough_to_run_the_rag_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    """花了 embedding 与 NLI 的钱，却要求先签一份行情同意书，是拦错人。"""
    item, = gate(
        monkeypatch,
        [FakeItem(frozenset({"live_rag"}))],
        present=(RAG_CONSENT,),
        **{"--run-live": True, "--run-live-rag": True},
    )

    assert item.reasons == []


def test_market_tests_are_still_gated_by_the_data_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """改窄了别人的门禁就不是修 bug 了，所以这一条与上面那条成对存在。"""
    item, = gate(
        monkeypatch,
        [FakeItem(frozenset({"live"}))],
        present=(RAG_CONSENT,),
        **{"--run-live": True, "--run-live-rag": True},
    )

    assert item.reasons == [DATA_REASON]


def test_the_llm_gate_does_not_accept_the_data_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item, = gate(
        monkeypatch,
        [FakeItem(frozenset({"live_llm"}))],
        present=(DATA_CONSENT, RAG_CONSENT),
        **{"--run-live": True, "--run-live-llm": True, "--run-live-rag": True},
    )

    assert item.reasons == [LLM_REASON]


def test_the_option_alone_does_not_open_a_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """命令行开关是意图，同意书是授权；只有意图时必须仍然拦住。"""
    item, = gate(
        monkeypatch,
        [FakeItem(frozenset({"live", "live_llm", "live_rag"}))],
        **{"--run-live": True, "--run-live-llm": True, "--run-live-rag": True},
    )

    assert sorted(item.reasons) == sorted([DATA_REASON, LLM_REASON, RAG_REASON])


def test_an_ordinary_test_is_touched_by_no_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    item, = gate(monkeypatch, [FakeItem(frozenset({"unit"}))])

    assert item.reasons == []
