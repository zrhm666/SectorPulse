"""JSONB 列的读法：驱动给对象，TEXT 列给字符串。

迁移 035 把资料库的 `*_json` 列全部转成了 JSONB，而 SQLite 上的同一批列仍然读作 TEXT。
psycopg 3 对 JSONB 直接返回已经解析好的 `list`/`dict`，所以再 `json.loads` 一次不是"多此
一举"，是对着一个 list 调用，抛 `TypeError`。

这个错误在离线夹具上永远看不见——SQLite 那一侧读的正是 TEXT，显式解析才对——所以规则只写在
一处。第二个实现会把它解释成另一个意思，已接纳证据的读取端就是这么坏的。
"""

from __future__ import annotations

import json
from typing import Any


def payload(value: Any) -> Any:
    """按列的真实类型取值：JSONB 已经是对象，TEXT 才需要解析。"""
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["payload"]
