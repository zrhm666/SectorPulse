from uuid import uuid4

import pytest

pytest.importorskip("aidynamic_agent")


def test_business_tool_factory_requires_every_registered_business_tool():
    from sector_pulse.infrastructure.agents.composition import AgentBusinessToolFactory

    factory = AgentBusinessToolFactory({"collect_market": lambda context: object()})

    with pytest.raises(ValueError, match="missing business tools"):
        factory.build(run_id=uuid4(), provider="fixture")


def test_business_tool_factory_returns_a_copy_for_each_run():
    from sector_pulse.infrastructure.agents.composition import (
        REQUIRED_BUSINESS_TOOL_NAMES,
        AgentBusinessToolFactory,
    )

    builders = {name: (lambda context, name=name: name) for name in REQUIRED_BUSINESS_TOOL_NAMES}
    factory = AgentBusinessToolFactory(builders)

    first = factory.build(run_id=uuid4(), provider="fixture")
    second = factory.build(run_id=uuid4(), provider="fixture")

    assert set(first) == set(REQUIRED_BUSINESS_TOOL_NAMES)
    assert first is not second
    assert first == second


def test_a1_business_tool_factory_builds_all_t01_to_t05_tools():
    from sector_pulse.domain.news.news_retrieval import SectorEntityConfig
    from sector_pulse.infrastructure.agents.composition import (
        A1BusinessToolFactory,
        A1ToolDependencies,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole, AgentToolContext

    dependencies = A1ToolDependencies(
        orchestration=object(),
        market_snapshots=object(),
        candidate_batches=object(),
        candidate_proposals=object(),
        news_batches=object(),
        news=object(),
        market=object(),
        constituents=object(),
        global_news=object(),
        keyword_news=object(),
        disclosure_news=object(),
        entity_config=SectorEntityConfig(
            version="test", aliases={}, industry_terms={}, ambiguous_terms=()
        ),
    )
    builders = A1BusinessToolFactory(dependencies).build(run_id=uuid4(), provider="fixture")
    context = AgentToolContext(
        task_id=uuid4(), attempt=1, role=AgentRole.A1, scope="data", worker_id="worker"
    )

    tools = {name: builder(context) for name, builder in builders.items()}

    assert set(tools) == {
        "collect_market",
        "inspect_data_quality",
        "rank_sector_candidates",
        "collect_initial_news",
        "propose_candidates",
    }


def test_composite_business_tool_factory_rejects_duplicate_or_incomplete_registry():
    from sector_pulse.infrastructure.agents.composition import (
        REQUIRED_BUSINESS_TOOL_NAMES,
        AgentBusinessToolFactory,
        CompositeBusinessToolFactory,
    )

    first_names = list(REQUIRED_BUSINESS_TOOL_NAMES)[:7]
    second_names = list(REQUIRED_BUSINESS_TOOL_NAMES)[7:]
    first = AgentBusinessToolFactory(
        {name: (lambda context, name=name: name) for name in first_names},
        required_names=frozenset(first_names),
    )
    second = AgentBusinessToolFactory(
        {name: (lambda context, name=name: name) for name in second_names},
        required_names=frozenset(second_names),
    )
    complete = CompositeBusinessToolFactory(first, second).build(
        run_id=uuid4(), provider="fixture"
    )
    assert set(complete) == set(REQUIRED_BUSINESS_TOOL_NAMES)

    with pytest.raises(ValueError, match="duplicate business tools"):
        CompositeBusinessToolFactory(first, first).build(run_id=uuid4(), provider="fixture")


def test_a2_business_tool_factory_registers_research_and_evidence_tools():
    from sector_pulse.infrastructure.agents.composition import (
        A2BusinessToolFactory,
        A2ToolDependencies,
    )

    deps = A2ToolDependencies(
        orchestration=object(),
        selections=object(),
        candidate_batches=object(),
        market_snapshots=object(),
        news=object(),
        news_batches=object(),
        research_searches=object(),
        news_details=object(),
        evidence_inspections=object(),
        sector_analyses=object(),
        detail=object(),
        keyword_news=object(),
    )

    builders = A2BusinessToolFactory(deps).build(run_id=uuid4(), provider="fixture")

    assert set(builders) == {
        "search_news",
        "read_news_detail",
        "inspect_evidence",
        "submit_analysis",
    }


def test_a3_a4_business_tool_factory_registers_editorial_and_review_tools():
    from sector_pulse.application.review.governance_service import GovernanceService
    from sector_pulse.infrastructure.agents.composition import (
        A3A4BusinessToolFactory,
        A3A4ToolDependencies,
    )

    deps = A3A4ToolDependencies(
        orchestration=object(),
        selections=object(),
        analyses=object(),
        outlines=object(),
        drafts=object(),
        news_evidence=object(),
        reviews=object(),
        draft_rules=object(),
        governance=GovernanceService(),
    )

    builders = A3A4BusinessToolFactory(deps).build(run_id=uuid4(), provider="fixture")

    assert set(builders) == {
        "submit_outline",
        "submit_draft",
        "submit_revision",
        "check_draft_rules",
        "submit_review",
    }
