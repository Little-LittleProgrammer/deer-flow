# Repository Guidelines

## Project Structure & Module Organization
DeerFlow is split into `frontend/` and `backend/`. Use `frontend/src/app` for Next.js routes, `frontend/src/components` for UI, and `frontend/src/core` for client-side domain logic. Static assets and demo data live in `frontend/public/`. Backend entrypoints live in `backend/app/`, shared harness code lives in `backend/packages/harness/`, and Python tests live in `backend/tests/`. Keep repo-level automation in `scripts/`, Docker assets in `docker/`, and reusable skills in `skills/public/`.

## Build, Test, and Development Commands
Run `make check` first to verify local prerequisites. Use `make install` to install Python and pnpm dependencies, then `make dev` to start the full local stack behind nginx on `localhost:2026`. Prefer `make docker-init` and `make docker-start` for the recommended Docker workflow. For focused work, use `cd frontend && pnpm dev`, `cd frontend && pnpm build`, `cd backend && make dev`, or `cd backend && make gateway`.

## Coding Style & Naming Conventions
TypeScript uses ESLint and Prettier; run `cd frontend && pnpm check` before submitting changes. Follow existing 2-space indentation in frontend files, `PascalCase` for React components, and `kebab-case` or route-segment naming under `src/app`. Python follows Ruff, PEP 8, and 4-space indentation; run `cd backend && make lint`. Name backend tests as `test_<feature>.py`, and keep harness code isolated from `backend/app` imports.

## Testing Guidelines
Backend coverage is pytest-based and lives in `backend/tests/`. Run `cd backend && make test` for the standard suite, or `PYTHONPATH=. uv run pytest tests/test_<feature>.py -v` for targeted checks. The frontend currently relies on static validation instead of a dedicated unit test runner, so treat `cd frontend && pnpm check` as required for every change. Only merge code that passes lint and syntax/type validation.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commits, for example `feat(docker): ...`, `fix(ui): ...`, and `docs: ...`. Keep commit scopes short and meaningful. Pull requests should explain the user-visible change, note config or migration impact, link the related issue, and include screenshots or GIFs for UI updates. Before opening a PR, confirm the relevant `make test`, `make lint`, and `pnpm check` commands pass locally.
