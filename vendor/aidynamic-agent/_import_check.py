#!/usr/bin/env python3
import sys

project_root = "/Users/a1234/Documents/project/new_agent"
sys.path.insert(0, project_root)

modules = [
    "aidynamic_agent.core.message",
    "aidynamic_agent.core.context",
    "aidynamic_agent.core.agent",
    "aidynamic_agent.llm.base",
    "aidynamic_agent.llm.factory",
    "aidynamic_agent.llm.providers.openai",
    "aidynamic_agent.llm.providers.anthropic",
    "aidynamic_agent.llm.adapters.base",
    "aidynamic_agent.llm.adapters.openai_adapter",
    "aidynamic_agent.llm.adapters.anthropic_adapter",
    "aidynamic_agent.llm.exceptions",
    "aidynamic_agent.tools.base",
    "aidynamic_agent.tools.registry",
    "aidynamic_agent.tools.context",
    "aidynamic_agent.tools.builtins",
    "aidynamic_agent.tools.builtins.bash",
    "aidynamic_agent.tools.builtins.file_ops",
    "aidynamic_agent.tools.builtins.glob",
    "aidynamic_agent.tools.builtins.history",
    "aidynamic_agent.tools.builtins.skill",
    "aidynamic_agent.tools.builtins.todo",
    "aidynamic_agent.tools.builtins.task",
    "aidynamic_agent.hooks.base",
    "aidynamic_agent.hooks.builtin",
    "aidynamic_agent.hooks",
    "aidynamic_agent.config",
    "aidynamic_agent.managers.state",
    "aidynamic_agent.managers.todo",
    "aidynamic_agent.managers.skill",
    "aidynamic_agent.managers.history",
    "aidynamic_agent.agents.factory",
    "aidynamic_agent.agents.parent",
    "aidynamic_agent.agents.sub",
    "aidynamic_agent.legacy",
]

passed = 0
failed = []

for mod in modules:
    try:
        __import__(mod)
        passed += 1
        print(f"OK: {mod}")
    except Exception as e:
        failed.append((mod, str(e)))
        print(f"FAIL: {mod} -> {e}")

print(f"\n{'='*50}")
print(f"Passed: {passed}/{len(modules)}")

if failed:
    print(f"Failed: {len(failed)}")
    for mod, err in failed:
        print(f"  {mod}: {err}")
