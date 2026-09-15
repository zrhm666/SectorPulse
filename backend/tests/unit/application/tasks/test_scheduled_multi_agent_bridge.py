from uuid import uuid4


def test_scheduled_bridge_starts_multi_agent_command_when_configured():
    from sector_pulse.application.tasks.scheduled_data_bridge import ScheduledDataRunBridge

    class Commands:
        def __init__(self):
            self.calls = []

        def create(self, input_json, provider="live", *, selection_policy="manual"):
            self.calls.append((input_json, provider, selection_policy))
            return uuid4()

    class Schedule:
        mode = "post_close"
        input_template = {"goal": "scheduled research"}

    commands = Commands()
    bridge = ScheduledDataRunBridge(
        object(), object(), object(), object(), multi_agent_commands=commands
    )

    run_id = bridge.start(uuid4(), Schedule())

    assert run_id is not None
    assert commands.calls == [
        ({"goal": "scheduled research"}, "live", "server_default")
    ]
