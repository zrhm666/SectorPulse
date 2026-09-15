# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2025-08-14

### Added

- Engineering-standard project setup mirroring deeplogic-cli
- `.pre-commit-config.yaml` with ruff and conventional-pre-commit hooks
- `.codeup/codeup.yml` CI/CD pipeline for lint/test/build/publish
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `docs/MR_TEMPLATE.md`
- `__version__` literal in `aidynamic_agent/__init__.py` for semantic-release

### Fixed

- Rename top-level package from `agent` to `aidynamic_agent` for correct PyPI distribution
- Fix run-loop bug where empty END_TURN responses incorrectly continued looping
- Fix 18 stale test failures including pytest-asyncio event loop pollution
- Fix `is_closed` method call bug in OpenAIProvider/AnthropicProvider (was attribute access)

### Changed

- Enable ruff format and mypy with strict type checking
- Add pyproject.toml config for ruff (E/W/F/I/B/UP) and mypy with pydantic plugin
- Add `_ensure_context()` method for None-safe context access in async code