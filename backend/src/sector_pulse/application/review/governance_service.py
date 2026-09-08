from dataclasses import dataclass

from sector_pulse.domain.article import ArticleDraft


@dataclass(frozen=True)
class GovernanceReport:
    status: str
    issues: tuple[dict[str, str], ...]
    rules_version: str = "phase2b-v1"


class GovernanceService:
    _FORBIDDEN_TERMS = ("建议买入", "建议卖出", "目标价", "保证收益", "稳赚")

    def check(self, draft: ArticleDraft) -> GovernanceReport:
        issues: list[dict[str, str]] = []
        source_ids = {source.source_id for source in draft.sources}
        referenced = {
            source_id for section in draft.sections for source_id in section.source_ids
        }
        if not source_ids or not referenced.issubset(source_ids):
            issues.append({"code": "SOURCE_UNBOUND", "message": "段落存在未绑定的可信来源"})
        text = "\n".join(
            (draft.introduction, draft.conclusion, draft.risk_notice)
            + tuple(section.body for section in draft.sections)
        )
        for term in self._FORBIDDEN_TERMS:
            if term in text:
                issues.append({"code": "FORBIDDEN_TRADING_LANGUAGE", "message": term})
        return GovernanceReport(
            status="FAIL" if issues else "PASS", issues=tuple(issues)
        )
