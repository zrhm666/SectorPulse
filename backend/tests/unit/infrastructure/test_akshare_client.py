from threading import Lock
from time import sleep

import pandas as pd
import pytest
from sector_pulse.domain.market import SectorKind
from sector_pulse.infrastructure.providers.akshare import client as client_module
from sector_pulse.infrastructure.providers.akshare.client import PandasThsAkShareClient


async def test_ths_industry_merges_name_codes_with_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client_module.ak,
        "stock_board_industry_name_ths",
        lambda: pd.DataFrame([{"name": "半导体", "code": "881121"}]),
    )
    monkeypatch.setattr(
        client_module.ak,
        "stock_board_industry_summary_ths",
        lambda: pd.DataFrame(
            [
                {
                    "板块": "半导体",
                    "涨跌幅": 2.3,
                    "上涨家数": 20,
                    "下跌家数": 4,
                    "领涨股": "测试股份",
                    "领涨股-涨跌幅": 9.8,
                }
            ]
        ),
    )

    batch = await PandasThsAkShareClient().fetch(SectorKind.INDUSTRY)

    assert batch.rows == [
        {
            "name": "半导体",
            "code": "881121",
            "板块": "半导体",
            "涨跌幅": 2.3,
            "上涨家数": 20,
            "下跌家数": 4,
            "领涨股": "测试股份",
            "领涨股-涨跌幅": 9.8,
        }
    ]


async def test_ths_industry_rejects_incomplete_name_join(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client_module.ak,
        "stock_board_industry_name_ths",
        lambda: pd.DataFrame([{"name": "半导体", "code": "881121"}]),
    )
    monkeypatch.setattr(
        client_module.ak,
        "stock_board_industry_summary_ths",
        lambda: pd.DataFrame([{"板块": "白酒", "涨跌幅": 1.0}]),
    )

    with pytest.raises(ValueError, match="THS industry field contract mismatch"):
        await PandasThsAkShareClient().fetch(SectorKind.INDUSTRY)


async def test_ths_industry_calls_v8_backed_sources_sequentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = Lock()
    active_calls = 0
    overlapping_call = False

    def track_call(frame: pd.DataFrame) -> pd.DataFrame:
        nonlocal active_calls, overlapping_call
        with lock:
            active_calls += 1
            overlapping_call = overlapping_call or active_calls > 1
        sleep(0.05)
        with lock:
            active_calls -= 1
        return frame

    monkeypatch.setattr(
        client_module.ak,
        "stock_board_industry_name_ths",
        lambda: track_call(pd.DataFrame([{"name": "半导体", "code": "881121"}])),
    )
    monkeypatch.setattr(
        client_module.ak,
        "stock_board_industry_summary_ths",
        lambda: track_call(pd.DataFrame([{"板块": "半导体", "涨跌幅": 2.3}])),
    )

    await PandasThsAkShareClient().fetch(SectorKind.INDUSTRY)

    assert overlapping_call is False


async def test_ths_concept_remains_name_code_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client_module.ak,
        "stock_board_concept_name_ths",
        lambda: pd.DataFrame([{"name": "AI 概念", "code": "309000"}]),
    )

    batch = await PandasThsAkShareClient().fetch(SectorKind.CONCEPT)

    assert batch.rows == [{"name": "AI 概念", "code": "309000"}]
