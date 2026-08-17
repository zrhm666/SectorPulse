import pytest
from sector_pulse.web.run_service import ProviderUnavailable

from backend.tests.unit.web.test_run_service import _service


def test_live_preflight_rejects_before_run_insert(monkeypatch, tmp_path) -> None:
    service = _service(tmp_path)
    monkeypatch.setattr("sector_pulse.web.live_provider.check_live_consent", lambda: False)
    with pytest.raises(ProviderUnavailable, match="live-llm-consent"):
        service.create_run({}, "live")
    assert service._runs_repo.list_runs() == []