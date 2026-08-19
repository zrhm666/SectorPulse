from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


class ProviderPlugin(Protocol):
    plugin_id: str

    def build(self, **config: Any) -> object: ...


@dataclass(frozen=True)
class PluginLoadResult:
    plugin_id: str
    available: bool
    provider: object | None = None
    error: str | None = None


class ProviderPluginRegistry:
    """显式注册 Provider 插件；单个插件失败不会阻断核心服务启动。"""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., object]] = {}

    def register(self, plugin_id: str, factory: Callable[..., object]) -> None:
        if not plugin_id.strip():
            raise ValueError("plugin_id is required")
        self._factories[plugin_id] = factory

    def load(self, plugin_id: str, **config: Any) -> PluginLoadResult:
        factory = self._factories.get(plugin_id)
        if factory is None:
            return PluginLoadResult(
                plugin_id=plugin_id, available=False, error="plugin not registered"
            )
        try:
            return PluginLoadResult(plugin_id=plugin_id, available=True, provider=factory(**config))
        except Exception as exc:  # 插件边界必须隔离异常
            return PluginLoadResult(plugin_id=plugin_id, available=False, error=str(exc))
