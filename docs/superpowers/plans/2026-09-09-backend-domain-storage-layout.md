# Backend Domain and Storage Layout Implementation Plan

> **For agentic workers:** Use executing-plans in the current session, as requested by the user. No subagents.

**Goal:** Complete the approved domain, storage and router organization without changing runtime behavior.

**Architecture:** Retain technical layers; group cohesive business modules within domain and both storage dialects. Split storage protocols and the mixed router at existing definition boundaries.

**Tech Stack:** Python 3.12+, FastAPI, SQLite, PostgreSQL, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-08-backend-domain-storage-layout-design.md` (approved 2026-09-09).

## Global constraints

- No new runtime dependencies; HTTP/CLI, models, SQL, transactions and migrations remain unchanged.
- No business database writes or live provider/LLM calls. PostgreSQL tests require an isolated database.
- Update imports and string patches; no compatibility forwarding shells.
- Work on `codex/backend-domain-storage-layout` in the current directory; do not merge or push without authorization.

## Task 1: Domain

Files: domain migration table in the spec; all Python consumers; `backend/tests/unit/test_package_layout.py`.

Consumes/produces: existing domain classes and functions, unchanged signatures, under the specified new module paths.

- [x] Run the existing package tests as a baseline (5 passed).
- [x] Add a failing package constraint and import test:

```python
def test_domain_root_contains_only_shared_contracts():
    assert {p.name for p in (ROOT / "domain").glob("*.py")} == {
        "__init__.py", "provider.py", "llm.py"
    }
```

- [x] Run `.venv/Scripts/python.exe -m pytest backend/tests/unit/test_package_layout.py -q -p no:cacheprovider` and observe failure before moving files.
- [x] Move the 19 modules exactly as specified, add docstring-only package initializers, and replace fully qualified module references in tracked Python consumers in one pass.
- [x] Include domain in network-forbidden import tests. Run package and domain-related unit tests; check no upward dependencies or resource path regressions.

## Task 2: Storage implementations and contracts

Files: both dialects and ports migration tables in the spec; `storage/runtime_bundle.py`; consumers and tests.

Consumes/produces: unchanged database wrappers, repository APIs and runtime-checkable protocols.

- [x] Add root and symmetry assertions that fail against ungrouped repositories:

```python
@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
def test_storage_dialect_root_is_small(dialect):
    assert {p.name for p in (ROOT / "storage" / dialect).glob("*.py")} == {
        "__init__.py", "database.py", "operations_query.py"
    }
```

- [x] Run package tests and observe expected failure.
- [x] Move repositories using the explicit spec mapping, keeping database.py in place. Split ports at AST class boundaries, preserving decorators, class bodies and inheritance. Rewrite each `from sector_pulse.storage.ports import ...` into imports from its owning module.
- [x] Remove unused imports with Ruff only in split files. Run storage/unit/contract tests and package migration resource tests against temporary SQLite files.

## Task 3: Router split

Files: `web/routers/runs.py`, `web/routers/review.py`, app/dependency consumers; package tests.

Consumes/produces: unchanged `build_runs_review_router`, `ReviewRouterDependencies`, `build_review_governance_router` signatures and route declarations.

- [x] Add import assertions for both new router modules; run and observe failure.
- [x] Record OpenAPI from a temporary SQLite-configured app without entering its lifespan. Move intact definitions at the dataclass boundary and rewrite named imports to their owning modules.
- [x] Compare the full OpenAPI object after the move; run Web contract and integration tests. Do not change tags or factory names (operation identifiers must remain stable).

## Task 4: Integration, documentation and acceptance

Files: README.md; this plan; new acceptance document under `docs/superpowers/plans/`.

- [x] Update the README backend tree and link the authoritative full migration table.
- [x] Scan tracked Python for stale module paths, `__file__`, dynamic import and string patch references. Confirm SQL diff is empty.
- [x] Run `.venv/Scripts/python.exe -m pytest backend/tests -m "not live and not live_llm and not postgres" -q -p no:cacheprovider` with database URL cleared.
- [x] Run Ruff and mypy, wheel build/package smoke, CLI help and the existing HTTP runtime smoke script using a temporary database.
- [ ] Inspect the existing PostgreSQL validation helper; run only with its isolated test database guard satisfied. Record any unavailable prerequisite explicitly.
- [x] Run `npm test` and `npm run build` in web using the installed Node runtime.
- [x] Review diff for non-import behavioral changes, record exact verification totals and exclusions, commit the completed refactor on the feature branch. Do not merge or push.

PostgreSQL status: local server is running, but the configured account cannot CREATE DATABASE. No database was created, and no business database was tested or modified. Live PostgreSQL verification remains pending a dedicated test URL; see the acceptance report.
