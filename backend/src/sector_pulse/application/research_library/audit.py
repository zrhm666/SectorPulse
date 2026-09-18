"""审计与普通日志各能说什么（规格 20.1）。

一次检索的审计要能回答"这个答案凭什么给出来"：问了什么、语料是哪一代、召回与重排的
名次、交出去的是哪几段、花了多少调用。唯一**不能**回答的是"正文说了什么"——正文留在
权威库里，由切片 ID 指回去。这不是为了省空间，而是为了让审计与日志活得比文档长：一份
被删掉的资料，它的正文仍然会出现在每一个曾经记下它的地方。

三条边界在这里划下：

**结果引用只装身份，不装内容。** `safe_result_reference` 只接受标识符字符集，遇到别的
东西就拒绝，而且拒绝时**不复述**那一段——把正文写进异常消息，等于从另一扇门把它放回
日志里。

**审计里的候选只留句柄与定位。** `candidate_reference` 从候选上减掉正文，其余原样保留。
减法而不是加法：将来候选多一个字段时，忘掉的是"它没被记下来"，而不是"它被悄悄记下来
了"。

**普通日志比审计更窄。** `retrieval_log_entry` 留下的只有身份与计数：审计是给排查的人
看的，日志是给所有人和所有采集器看的，两者的范围不该一样大。
"""

from __future__ import annotations

import re

from pydantic import AwareDatetime, Field
from sector_pulse.domain.research_library.models import Record
from sector_pulse.domain.research_library.retrieval import (
    RetrievalAuditRecord,
    RetrievedCandidate,
)

__all__ = [
    "MAX_REFERENCE_LENGTH",
    "RetrievalLogEntry",
    "UnsafeResultReference",
    "candidate_reference",
    "retrieval_log_entry",
    "safe_result_reference",
]

#: 结果引用最终写进 `ToolInvocation.result_reference`，那里的上限是 512。
MAX_REFERENCE_LENGTH = 512

#: 一段引用必须是一个标识符：字母数字开头，其后只允许 `. _ : + -`。
#: 中文、空格、换行、引号、大括号都不在其中——正文里这些字符随便出现一个。
_REFERENCE_PART = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}\Z")

#: 审计条目里**不**进结果引用的字段：正文（这一层要挡住的）与检索 ID（条目属于这次
#: 检索，再抄一份检索 ID 只会多出两个可能对不上的副本）。
_DROPPED_FROM_CANDIDATE = ("text", "retrieval_id")


class UnsafeResultReference(ValueError):
    """一段结果引用不是标识符。

    消息里只有长度，没有原文：这个异常会被日志、告警与工单系统转抄，把被拒绝的那一段
    放进去，`safe_result_reference` 就成了把正文送出去的最短路径。
    """


def safe_result_reference(*parts: str) -> str:
    """把若干标识符拼成一条可以写进审计与账本的结果引用。

    每一段都必须自己就是标识符，中间用 `/` 连接。空段与超长段一律拒绝：跳过空段会让
    引用静默地变短（`a//b` 与 `a/b` 从此是同一条），超长段会撞上账本字段的长度上限。
    """
    if not parts:
        raise UnsafeResultReference("a result reference needs at least one part")
    for part in parts:
        if not _REFERENCE_PART.match(part):
            raise UnsafeResultReference(
                f"a result reference part must be a plain identifier; got {len(part)} characters"
            )
    reference = "/".join(parts)
    if len(reference) > MAX_REFERENCE_LENGTH:
        raise UnsafeResultReference(
            f"a result reference must fit in {MAX_REFERENCE_LENGTH} characters; "
            f"got {len(reference)}"
        )
    return reference


def candidate_reference(candidate: RetrievedCandidate) -> dict[str, object]:
    """一条候选的安全引用：句柄、定位与名次都在，正文不在。

    它同时也是 `inspect` 的授权名单（`chunk_id` 是查正文用的键），因此不能只剩一个
    `candidate_id`——那样查回来的是"这次检索发过某个句柄"，而不是"发过哪一段"。
    """
    payload = candidate.model_dump(mode="json")
    for dropped in _DROPPED_FROM_CANDIDATE:
        payload.pop(dropped)
    return payload


class RetrievalLogEntry(Record):
    """一条普通的检索日志。

    只有身份与计数：哪个 run/任务/角色、哪一代语料、召回与重排各多少条、Provider 调用
    几次、花了多久。问题文本与候选正文都不在——`RetrievalAuditRecord` 里有它们，而那份
    记录的去处是可审计的存储，不是日志采集器。
    """

    retrieval_id: str = Field(min_length=1)
    run_id: str | None = None
    task_id: str | None = None
    attempt_id: int | None = Field(default=None, ge=0)
    role: str | None = None
    corpus_generation: str = Field(min_length=1)
    query_fingerprint: str = Field(min_length=1)
    fused: int = Field(default=0, ge=0)
    reranked: int = Field(default=0, ge=0)
    returned: int = Field(default=0, ge=0)
    provider_calls: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    created_at: AwareDatetime


def retrieval_log_entry(audit: RetrievalAuditRecord) -> RetrievalLogEntry:
    """把一份审计投影成一条可以进普通日志的记录。"""
    return RetrievalLogEntry(
        retrieval_id=audit.retrieval_id,
        run_id=audit.run_id,
        task_id=audit.task_id,
        attempt_id=audit.attempt_id,
        role=audit.role,
        corpus_generation=audit.corpus_generation,
        query_fingerprint=audit.query_fingerprint,
        fused=len(audit.fused_candidates),
        reranked=len(audit.reranked_candidates),
        returned=len(audit.returned_evidence),
        provider_calls=audit.provider_calls,
        duration_ms=audit.duration_ms,
        created_at=audit.created_at,
    )
