import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("legacy_mode", ["workflow", "agent"])
def test_new_run_request_rejects_legacy_mode_at_any_request_level(legacy_mode):
    from sector_pulse.web.schemas.runs import NewRunRequest

    with pytest.raises(ValidationError, match="attribution_mode.*removed"):
        NewRunRequest.model_validate(
            {
                "provider": "fixture",
                "input_json": {"attribution_mode": legacy_mode},
            }
        )
    with pytest.raises(ValidationError):
        NewRunRequest.model_validate(
            {
                "provider": "fixture",
                "input_json": {},
                "attribution_mode": legacy_mode,
            }
        )


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
