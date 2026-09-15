"""The human release audit must stay human, and an export must stay an article.

Approval, revocation, evidence decisions and the export record all carry an actor
that comes from the caller's header and a timestamp from the server clock. If an
agent could produce any of those rows it could manufacture a release decision
nobody made, so this file pins the two ways that must remain impossible:

* the agent's tool surface holds no governance action and no governance port;
* the product surface derives actor, version and time from the request header and
  the stored draft, never from a request body an agent could compose.

The last test pins the other half of the same sentence: an approved export is the
article, and carries nothing from the scheduler.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

pytest.importorskip("aidynamic_agent")

# Every write that leaves a human release trace behind.
HUMAN_GOVERNANCE_ACTIONS = frozenset(
    {
        "approve_draft",
        "revoke_draft",
        "return_draft",
        "export_approved_json",
        "record_export",
        "record_evidence_decision",
    }
)

DRAFT_FIELDS = frozenset(
    {
        "draft_id",
        "run_id",
        "version",
        "status",
        "titles",
        "introduction",
        "sections",
        "conclusion",
        "risk_notice",
        "sources",
        "character_count",
    }
)


def test_no_agent_role_can_call_a_human_governance_action() -> None:
    from sector_pulse.infrastructure.agents.composition import REQUIRED_BUSINESS_TOOL_NAMES
    from sector_pulse.infrastructure.agents.roles import ROLE_TOOL_NAMES

    assert frozenset() == REQUIRED_BUSINESS_TOOL_NAMES & HUMAN_GOVERNANCE_ACTIONS
    for role, names in ROLE_TOOL_NAMES.items():
        assert names & HUMAN_GOVERNANCE_ACTIONS == frozenset(), role


def test_the_business_tool_factory_refuses_a_governance_tool_from_a_builder() -> None:
    """The whitelist is enforced when tools are built, not merely documented."""
    from sector_pulse.infrastructure.agents.composition import (
        REQUIRED_BUSINESS_TOOL_NAMES,
        AgentBusinessToolFactory,
    )

    builders = {name: (lambda: None) for name in REQUIRED_BUSINESS_TOOL_NAMES}
    builders["approve_draft"] = lambda: None

    with pytest.raises(ValueError, match="unexpected business tools: approve_draft"):
        AgentBusinessToolFactory(builders).build(run_id=uuid4(), provider="fixture")


def test_the_editorial_agent_factory_holds_no_human_audit_repository() -> None:
    """A3/A4 can check governance but are never handed the audit it writes to."""
    import typing
    from dataclasses import fields

    from sector_pulse.infrastructure.agents.composition import A3A4ToolDependencies
    from sector_pulse.storage.ports.review import (
        GovernanceRepositoryPort,
        ReleaseAuditRepositoryPort,
    )

    audit_ports = (ReleaseAuditRepositoryPort, GovernanceRepositoryPort)
    hints = typing.get_type_hints(A3A4ToolDependencies)
    held = {
        field.name: hints[field.name]
        for field in fields(A3A4ToolDependencies)
        if isinstance(hints[field.name], type)
        and issubclass(hints[field.name], audit_ports)
    }
    assert held == {}


def _app_with_draft(tmp_path):
    from fastapi.testclient import TestClient
    from sector_pulse.domain.writing.article import (
        ArticleDraft,
        ArticleSection,
        ArticleSource,
        DraftStatus,
    )
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.writing.phase1b_repository import (
        SQLitePhase1BRepository,
    )
    from sector_pulse.web.app import create_app

    database_path = tmp_path / "release-audit.db"
    database = SQLiteDatabase(database_path)
    draft = ArticleDraft(
        draft_id=uuid4(),
        run_id=uuid4(),
        version=1,
        status=DraftStatus.INCOMPLETE,
        titles=("板块观察",),
        introduction="导语",
        sections=(
            ArticleSection(
                section_id="section-1",
                sector_id="sector-1",
                heading="板块",
                body="正文",
                claims=(),
                source_ids=("source-1",),
                character_count=2,
            ),
        ),
        conclusion="结论",
        risk_notice="市场有风险",
        sources=(
            ArticleSource(
                source_id="source-1",
                title="来源",
                citation_url="https://example.test/source",
            ),
        ),
        character_count=8,
    )
    SQLitePhase1BRepository(database).save_draft(draft)
    return TestClient(create_app(database_path=database_path)), draft


def test_approval_actor_and_version_come_from_the_header_not_the_body(tmp_path) -> None:
    """A composed request body must not be able to name the approver or the version."""
    client, draft = _app_with_draft(tmp_path)
    base = f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}"

    response = client.post(
        f"{base}/approve",
        headers={"X-Actor": "editor-on-duty"},
        json={"actor": "attacker", "version": 99, "approved_at": "1999-01-01T00:00:00Z"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "draft_id": str(draft.draft_id),
        "version": 1,
        "status": "APPROVED_FOR_COPY",
        "actor": "editor-on-duty",
    }
    recorded = client.get(f"{base}/approval").json()
    assert recorded["actor"] == "editor-on-duty"
    assert recorded["version"] == 1


def test_an_advanced_draft_does_not_inherit_the_earlier_approval(tmp_path) -> None:
    """Approving one version must not release text that version never contained."""
    from hashlib import sha256

    client, draft = _app_with_draft(tmp_path)
    base = f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}"
    approved = client.post(f"{base}/approve", headers={"X-Actor": "editor-on-duty"})
    assert approved.status_code == 200

    patched = client.post(
        f"{base}/patches",
        headers={"X-Actor": "editor-on-duty"},
        json={
            "base_version": 1,
            "operations": [
                {
                    "path": "introduction",
                    "old_value_hash": sha256(draft.introduction.encode()).hexdigest(),
                    "value": "人工改写后的导语",
                }
            ],
        },
    )
    assert patched.status_code == 201
    assert patched.json()["version"] == 2

    # The new version has no approval of its own...
    assert client.get(f"{base}/approval").json() is None
    # ...and must not be exportable on the strength of the old one.
    export = client.get(f"{base}/export.json", headers={"X-Actor": "editor-on-duty"})
    assert export.status_code == 409


def test_approval_and_revocation_are_time_stamped_by_the_server(tmp_path) -> None:
    """Actor and time are the two fields a composed request must not be able to set."""
    from datetime import UTC, datetime

    client, draft = _app_with_draft(tmp_path)
    base = f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}"
    # The audit store keeps whole seconds, so the window is compared at that
    # resolution rather than pretending to sub-second precision it never stored.
    before = datetime.now(UTC).replace(microsecond=0)
    client.post(f"{base}/approve", headers={"X-Actor": "approver-a"})

    revoked = client.post(
        f"{base}/revoke",
        headers={"X-Actor": "withdrawer-b"},
        json={"actor": "attacker", "created_at": "1999-01-01T00:00:00Z"},
    )

    assert revoked.status_code == 200
    assert revoked.json()["actor"] == "withdrawer-b"
    events = client.get(f"{base}/audit").json()
    assert [(item["event_type"], item["actor"]) for item in events] == [
        ("APPROVED", "approver-a"),
        ("REVOKED", "withdrawer-b"),
    ]
    for item in events:
        recorded = datetime.fromisoformat(item["created_at"])
        if recorded.tzinfo is None:
            # The store keeps naive UTC; the audit claim is about the clock, not
            # about the encoding.
            recorded = recorded.replace(tzinfo=UTC)
        assert before <= recorded <= datetime.now(UTC)


def test_an_approved_export_is_the_article_and_nothing_from_the_scheduler(tmp_path) -> None:
    client, draft = _app_with_draft(tmp_path)
    base = f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}"
    client.post(f"{base}/approve", headers={"X-Actor": "editor-on-duty"})

    exported = client.get(f"{base}/export.json", headers={"X-Actor": "editor-on-duty"})

    assert exported.status_code == 200
    assert set(exported.json()) == DRAFT_FIELDS
    serialized = exported.text
    for scheduler_term in (
        "dispatch",
        "tool_invocation",
        "budget",
        "ledger",
        "task_id",
        "revision",
        "lease",
        "attempt",
    ):
        assert scheduler_term not in serialized, scheduler_term
