"""从安装包资源读取可重复的 Phase 1B Fixture。"""

import json
from importlib.resources import files
from typing import cast


def load_default_fixture_responses() -> dict[str, object]:
    """读取正式运行 Fixture；运行时代码不依赖 backend/tests。"""
    resource = files("sector_pulse.resources").joinpath(
        "phase1b/fixture_responses.json"
    )
    raw = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("default fixture responses must be an object")
    return cast(dict[str, object], raw)
