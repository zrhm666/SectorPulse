from uuid import uuid4

import pytest
from pydantic import ValidationError
from sector_pulse.application.writing.phase1b_pipeline import Phase1BRequest
from sector_pulse.web.schemas.data_run import GenerateDataRunRequest
from sector_pulse.web.services.run_service import ProviderUnavailable

from backend.tests.unit.web.services.test_run_service import _input_json, _service


def test_legacy_pipeline_keeps_its_default_while_new_generate_request_rejects_modes():
    payload = {**_input_json(), "run_id": uuid4()}
    assert Phase1BRequest.model_validate(payload).attribution_mode == "workflow"
    assert GenerateDataRunRequest().model_dump() == {}
    with pytest.raises(ValidationError):
        GenerateDataRunRequest.model_validate({"attribution_mode": "workflow"})
    with pytest.raises(ValidationError):
        Phase1BRequest.model_validate({**payload, "attribution_mode": "autonomous"})


async def test_workflow_mode_is_saved_exposed_and_inherited_by_retry(tmp_path):
    service = _service(tmp_path)
    original = service.create_run(_input_json(), "fixture")
    await service.wait(original)
    assert service._runs_repo.get_run(original).input_json["attribution_mode"] == "workflow"
    assert service.get_run(original).attribution_mode == "workflow"
    assert service.list_runs()[0].attribution_mode == "workflow"
    retry = service.retry_run(original)
    await service.wait(retry)
    assert service._runs_repo.get_run(retry).input_json["attribution_mode"] == "workflow"


def test_unavailable_agent_rejected_before_creating_a_run(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ProviderUnavailable, match="AGENT_MODE_UNAVAILABLE"):
        service.create_run({**_input_json(), "attribution_mode": "agent"}, "fixture")
    assert service.list_runs() == []


def test_service_rejects_unknown_mode_with_validation_error(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValidationError):
        service.create_run({**_input_json(), "attribution_mode": "typo"}, "fixture")
    assert service.list_runs() == []
