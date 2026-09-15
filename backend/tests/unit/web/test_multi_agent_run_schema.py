import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("legacy_key", ["attribution_mode", "workflow", "agent"])
def test_new_run_request_rejects_legacy_mode_at_any_request_level(legacy_key):
    from sector_pulse.web.schemas.runs import NewRunRequest

    with pytest.raises(ValidationError, match=f"{legacy_key}.*removed"):
        NewRunRequest.model_validate(
            {
                "provider": "fixture",
                "input_json": {legacy_key: "legacy-value"},
            }
        )
    with pytest.raises(ValidationError, match=f"{legacy_key}.*removed"):
        NewRunRequest.model_validate(
            {
                "provider": "fixture",
                "input_json": {},
                legacy_key: "legacy-value",
            }
        )


def test_multi_agent_summary_does_not_claim_a_removed_attribution_mode():
    from datetime import UTC, datetime
    from uuid import uuid4

    from sector_pulse.web.schemas.runs import RunSummary

    summary = RunSummary(
        run_id=uuid4(),
        execution_engine="multi_agent",
        requested_at=datetime.now(UTC),
        provider="fixture",
        status="WAITING",
        elapsed_ms=None,
        total_cost_cny="0",
        draft_id=None,
    )

    assert summary.attribution_mode is None


def test_new_run_request_rejects_unknown_provider_and_accepts_selection_policy():
    from sector_pulse.web.schemas.runs import NewRunRequest

    with pytest.raises(ValidationError):
        NewRunRequest.model_validate({"provider": "other", "input_json": {}})
    request = NewRunRequest.model_validate(
        {
            "provider": "fixture",
            "selection_policy": "server_default",
            "input_json": {},
        }
    )
    assert request.selection_policy == "server_default"
