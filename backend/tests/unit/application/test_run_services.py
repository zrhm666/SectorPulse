from uuid import uuid4

from sector_pulse.application.run_commands import RunCommandService
from sector_pulse.application.run_queries import RunQueryService


class Port:
    def __init__(self) -> None:
        self.run_id = uuid4()

    def create_run(self, input_json, provider):
        return self.run_id

    def cancel_run(self, run_id):
        return run_id == self.run_id

    def list_runs(self, limit=50):
        return ["summary"]

    def get_run(self, run_id):
        return "detail"

    def get_radar(self, run_id):
        return {"cards": []}

    def get_draft(self, run_id):
        return {"versions": []}

    def get_evidence(self, run_id):
        return {"events": []}

    def get_review(self, run_id):
        return {"decision": None}

    def render_draft_markdown(self, run_id):
        return "# draft"

    def render_draft_text(self, run_id):
        return "draft"


def test_command_service_delegates_to_port() -> None:
    port = Port()
    service = RunCommandService(port)
    assert service.create({"x": 1}) == port.run_id
    assert service.cancel(port.run_id) is True


def test_query_service_exposes_read_only_methods() -> None:
    port = Port()
    service = RunQueryService(port)
    assert service.list() == ["summary"]
    assert service.detail(port.run_id) == "detail"
    assert service.radar(port.run_id) == {"cards": []}
    assert service.markdown(port.run_id) == "# draft"
