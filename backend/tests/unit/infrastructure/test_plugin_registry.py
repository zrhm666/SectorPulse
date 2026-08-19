from sector_pulse.infrastructure.providers.plugin_registry import ProviderPluginRegistry


def test_plugin_failure_is_isolated() -> None:
    registry = ProviderPluginRegistry()
    registry.register("broken", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    result = registry.load("broken")
    assert result.available is False
    assert result.error == "boom"
    assert registry.load("missing").available is False
