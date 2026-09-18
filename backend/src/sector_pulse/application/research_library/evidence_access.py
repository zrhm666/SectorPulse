"""A3/A4 能引用的内部证据：这个 run 里已经接纳过、而且现在还站得住的那批（规格 15.3、15.4）。

A2 接纳的内部证据不会自己走进草稿。A3/A4 拿到的是一份 `internal_research_evidence` Artifact
的引用，读到的是一批带句柄的事实；引用一件事就是把那个句柄写进草稿。因此"这条引用还算不算
数"必须有一个统一答案，本模块就是它。

三条判断都落在这一处，因为它们在三个地方被问同一句话——A3 提交草稿时、A4 运行确定性检查时、
artifact reader 渲染证据时：

**当前尝试。** 一次任务重试会推进 attempt，上一轮留下的 Artifact 仍然在快照里，但它描述的是
一次已经被放弃的尝试。引它不算错，只是它不该再是新引用的来源。

**仍然生效的版本。** 一条事实站在某几版原文上；那些版本里只要有一版不再 ACTIVE，这条事实就
引用了一份已经从语料里退出的原文（规格 16.3）。资料删除与替换立刻生效，已经发出的引用不能
变成绕过它的通道。

**查不到就是站不住。** 索引里没有这个句柄时，`is_citable` 返回 False 而不是"无法判断"。一份
不存在的证据和一个失效的版本，对引用它的人来说后果一样。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from sector_pulse.application.research_library.artifacts import EVIDENCE_ARTIFACT_KIND
from sector_pulse.domain.orchestration.models import RunSnapshot
from sector_pulse.domain.research_library.retrieval import AcceptedEvidenceClaim
from sector_pulse.storage.ports.research_library import AcceptedEvidenceRepositoryPort


@dataclass(frozen=True)
class AcceptedEvidenceIndex:
    """一个 run 里被接纳的内部证据，按引用句柄索引。

    空索引是常态而不是异常：没有内部资料库的 run 就是这个样子。所有引用检查对空索引的回答
    都是"这条引用站不住"，因此接没接 RAG 都不会让一份无法核对的引用悄悄通过。
    """

    claims: Mapping[str, AcceptedEvidenceClaim] = field(default_factory=dict)
    active_version_ids: frozenset[str] = frozenset()

    def get(self, evidence_id: str) -> AcceptedEvidenceClaim | None:
        return self.claims.get(evidence_id)

    def is_citable(self, evidence_id: str) -> bool:
        """这条引用现在还能不能写进草稿：句柄要存在，它站的每一版都要还在架。"""
        claim = self.claims.get(evidence_id)
        if claim is None:
            return False
        return all(
            version_id in self.active_version_ids for version_id in claim.document_version_ids
        )

    def cited_versions(self) -> tuple[str, ...]:
        """索引里出现过的所有版本 id，按首次出现顺序去重。"""
        return tuple(
            dict.fromkeys(
                version_id
                for claim in self.claims.values()
                for version_id in claim.document_version_ids
            )
        )

    @classmethod
    def load(
        cls,
        *,
        snapshot: RunSnapshot,
        repository: AcceptedEvidenceRepositoryPort,
    ) -> AcceptedEvidenceIndex:
        references = _current_evidence_references(snapshot)
        if not references:
            return cls()
        claims = repository.get_accepted_evidence(references)
        index = cls(claims={claim.evidence_id: claim for claim in claims})
        return cls(
            claims=index.claims,
            active_version_ids=repository.load_active_version_ids(index.cited_versions()),
        )


def _current_evidence_references(snapshot: RunSnapshot) -> tuple[str, ...]:
    """快照里那些属于**当前尝试**的证据 Artifact 引用。

    只按引用找、不按任务角色找：接纳服务已经保证只有 A2 能写出这种 kind 的 Artifact，
    再在这里按角色筛一遍等于把同一条规则写两份。
    """
    attempts = {task.task_id: task.attempt for task in snapshot.tasks}
    return tuple(
        dict.fromkeys(
            artifact.reference
            for artifact in snapshot.artifacts
            if artifact.kind == EVIDENCE_ARTIFACT_KIND
            and attempts.get(artifact.task_id) == artifact.attempt
        )
    )


__all__ = ["AcceptedEvidenceIndex"]
