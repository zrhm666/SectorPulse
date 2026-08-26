# Soft Blue UI Acceptance

## Automated verification

- Frontend tests: `D:\software\nodejs\npm.cmd test` — 31 test files passed, 80 tests passed.
- Production build: `D:\software\nodejs\npm.cmd run build` — TypeScript and Vite completed successfully; fresh assets were written to `web/dist`.
- Backend regression: `.\.venv\Scripts\python.exe -m pytest` — 251 passed, 7 live tests skipped by their explicit consent flags.
- Design scan: `node C:\Users\18067\.codex\skills\impeccable\scripts\detect.mjs --json web/src` — 0 findings.

## Visual verification

- Desktop viewport: 1440 × 900.
- Narrow viewport: 390 × 844 (browser content viewport reported 375px after scrollbar reservation).
- Routes checked: `/`, `/runs`, `/runs/new`, `/data-runs/75c11bc0-abb4-47c7-9db5-05b5a9c16906`, `/runs/75c11bc0-abb4-47c7-9db5-05b5a9c16906`, `/review`, `/schedules`, `/system`, and `/shadow-acceptance`.
- No page-level horizontal overflow was found on the checked desktop or narrow routes.
- Mobile navigation opens from the labelled menu control, exposes its expanded state, and closes with Escape.
- Review workspace resolves to three desktop columns and one narrow-screen column; the center draft remains visually dominant on desktop.

## Defects fixed in the bounded QA pass

- Corrected the Vite development proxy and README startup URLs from stale port `8000` to the backend's actual port `9000`.
- Replaced the misleading review-queue fallback `0 个板块` with `板块数未提供` when the run summary omits `sector_count`.

## Functional invariants

- Application routes and backend API paths remain unchanged.
- Existing polling, filtering, pagination, retry, review, governance, scheduling, loading, empty, and error behavior remains covered by the frontend suite.
- Backend application code did not require a change; only the development proxy and startup documentation were corrected to match the existing server port.
- Status continues to use text and icons in addition to semantic color.
- Live external-provider tests were not invoked; this acceptance pass did not consume live data or LLM quota.

## Remaining warnings

- Vite reports deprecation warnings for the React plugin's `esbuild` options; these are upstream configuration warnings and do not fail tests or builds.
- Pytest reports one Starlette deprecation warning about the `httpx` TestClient compatibility path.
- Seven live tests remain intentionally skipped unless their `--run-live` or `--run-live-llm` flags are supplied.
