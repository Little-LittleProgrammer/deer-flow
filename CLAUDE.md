# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DeerFlow is a full-stack "super agent harness" that orchestrates sub-agents, memory, and sandboxes to do almost anything — powered by extensible skills.

**Stack**:
- Backend: Python 3.12+, LangGraph + FastAPI gateway, sandbox/tool system, MCP integration
- Frontend: Next.js 16 + React 19 + TypeScript 5.8 + Tailwind CSS 4 + pnpm 10.26.2
- Local dev entrypoint: `make dev` starts all services on `http://localhost:2026`

## Commands

### Root Directory (Full Application)

```bash
make check      # Check system requirements (Node.js 22+, pnpm, uv, nginx)
make install    # Install all dependencies (frontend + backend)
make config     # Generate local config files (first-time setup only)
make dev        # Start all services (LangGraph:2024, Gateway:8001, Frontend:3000, nginx:2026)
make stop       # Stop all services
```

### Backend Directory (`backend/`)

```bash
make install    # Install backend dependencies (uv sync)
make dev        # Run LangGraph server only (port 2024)
make gateway    # Run Gateway API only (port 8001)
make test       # Run all backend tests (pytest)
make lint       # Lint with ruff
make format     # Format code with ruff
```

### Frontend Directory (`frontend/`)

```bash
pnpm dev        # Dev server with Turbopack (port 3000)
pnpm build      # Production build (requires BETTER_AUTH_SECRET)
pnpm lint       # ESLint only
pnpm typecheck  # TypeScript type check
```

### Running a Single Backend Test

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_<feature>.py -v
```

## Architecture

### Service Topology

```
Browser → nginx (port 2026) ← Unified entry point
           ├→ Frontend (port 3000) ← / (non-API requests)
           ├→ Gateway API (port 8001) ← /api/models, /api/mcp, /api/skills, /api/threads/*/artifacts
           └→ LangGraph Server (port 2024) ← /api/langgraph/* (agent interactions)
```

### Project Structure

```
deer-flow/
├── Makefile                    # Root commands
├── config.yaml                 # Main application configuration
├── extensions_config.json      # MCP servers and skills configuration
├── backend/                    # Backend application
│   ├── packages/harness/       # deerflow-harness package (import: deerflow.*)
│   │   └── deerflow/
│   │       ├── agents/         # LangGraph agent system
│   │       ├── sandbox/        # Sandbox execution system
│   │       ├── subagents/      # Subagent delegation system
│   │       ├── mcp/            # MCP integration
│   │       ├── models/         # Model factory
│   │       ├── skills/         # Skills discovery
│   │       └── config/         # Configuration system
│   ├── app/                    # Application layer (import: app.*)
│   │   ├── gateway/            # FastAPI Gateway API
│   │   └── channels/           # IM platform integrations (Feishu, Slack, Telegram)
│   └── tests/                  # Test suite
├── frontend/                   # Next.js frontend
│   └── src/
│       ├── app/                # Next.js App Router
│       ├── components/         # React components
│       └── core/               # Business logic (threads, api, artifacts, i18n, settings)
└── skills/                     # Agent skills directory
    ├── public/                 # Built-in skills
    └── custom/                 # Custom skills (gitignored)
```

### Harness / App Split

The backend has a strict dependency boundary:

- **Harness** (`packages/harness/deerflow/`): Publishable agent framework. Import prefix: `deerflow.*`
- **App** (`app/`): Unpublished application code. Import prefix: `app.*`

**Rule**: App imports deerflow, but deerflow NEVER imports app. This is enforced by `tests/test_harness_boundary.py` in CI.

## Configuration

### Main Config (`config.yaml`)

Location: Project root (recommended) or `backend/` directory.

Key sections:
- `models[]` - LLM configurations with `use` class path, `supports_thinking`, `supports_vision`
- `sandbox.use` - Sandbox provider class path
- `skills.path` - Host path to skills directory
- `memory` - Memory system settings
- `subagents.enabled` - Master switch for subagent delegation
- `channels` - IM platform integrations (Feishu, Slack, Telegram)

Config values starting with `$` are resolved as environment variables (e.g., `$OPENAI_API_KEY`).

### Extensions Config (`extensions_config.json`)

Location: Project root (recommended) or `backend/` directory.

Contains:
- `mcpServers` - MCP server configurations
- `skills` - Skill enabled states

## Development Workflow

### Before Committing

Run these validation steps:

```bash
# Backend (required for CI)
cd backend && make lint && make test

# Frontend (if touched)
cd frontend && pnpm lint && pnpm typecheck

# Frontend build (if env/auth/routing changes)
BETTER_AUTH_SECRET=local-dev-secret pnpm build
```

### Test-Driven Development

Every new feature or bug fix MUST be accompanied by unit tests:

- Write tests in `backend/tests/` following naming convention `test_<feature>.py`
- Run `make test` before and after changes
- Tests must pass before feature is complete

### Documentation Update Policy

When making code changes, update relevant documentation:
- `README.md` for user-facing changes
- `backend/CLAUDE.md` for backend architecture changes
- `frontend/CLAUDE.md` for frontend architecture changes

## Key Patterns

### Import Conventions

```python
# Harness internal
from deerflow.agents import make_lead_agent

# App internal
from app.gateway.app import app

# App → Harness (allowed)
from deerflow.config import get_app_config

# Harness → App (FORBIDDEN)
# from app.gateway.routers.uploads import ...  # ← will fail CI
```

### Frontend Data Flow

1. User input → thread hooks (`core/threads/hooks.ts`) → LangGraph SDK streaming
2. Stream events update thread state (messages, artifacts, todos)
3. TanStack Query manages server state; localStorage stores user settings

### Sandbox Virtual Paths

- Agent sees: `/mnt/user-data/{workspace,uploads,outputs}`, `/mnt/skills`
- Physical: `backend/.deer-flow/threads/{thread_id}/user-data/...`

## Environment Variables

```bash
# API keys (set in .env or export)
OPENAI_API_KEY=your-key
TAVILY_API_KEY=your-key

# Frontend build
BETTER_AUTH_SECRET=local-dev-secret  # Required for production build

# Config path overrides
DEER_FLOW_CONFIG_PATH=/path/to/config.yaml
DEER_FLOW_EXTENSIONS_CONFIG_PATH=/path/to/extensions_config.json
```

## Common Gotchas

- `pnpm build` fails without `BETTER_AUTH_SECRET` — set it or use `SKIP_ENV_VALIDATION=1`
- Proxy env vars can break frontend `pnpm install`
- `make config` aborts if `config.yaml` already exists (by design)
- IM channels in Docker Compose use container service names (`http://langgraph:2024`), not `localhost`

## Detailed Architecture

For comprehensive architecture details, see:
- [backend/CLAUDE.md](backend/CLAUDE.md) — Backend architecture, agent system, middleware chain, sandbox, MCP, memory
- [frontend/CLAUDE.md](frontend/CLAUDE.md) — Frontend architecture, components, data flow, code style