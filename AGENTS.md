# DONNA — Agent Instructions

## Repository Structure

Monorepo with two independent stacks:
- **`frontend/`** — Angular 22 SPA (standalone, zoneless, signals)
- **`backend/`** — FastAPI + xcore plugin framework (Python 3.14, Poetry)
- **`mcp/`** — MCP server sub-projects (word, excel, memory, vision_ocr, referentiel_normatif)

## Frontend (`frontend/`)

### Quick Commands

```sh
cd frontend && npm install
npm run check          # lint:classes + lint:links + lint:i18n + build + test
npm run lint:classes   # Tailwind class conflicts
npm run lint:i18n      # i18n parity (Transloco, EN/FR)
npm run lint:links     # dead links
npm test               # vitest
npm run shots          # Playwright screenshots (4 widths)
npm run shots -- --lang=fr /workspace
npm run icons          # regenerate icons from lucide-static
```

### Key Conventions

- Angular 22 standalone, **zoneless**, signals — no NgZone, no traditional modules
- Tailwind v4 with design tokens in `src/styles.scss` — use `max-w-page` / `max-w-measure` / `max-w-form` / `max-w-aside` (never raw spacing tokens for container widths)
- Transloco for i18n — EN is default, FR runtime switch
- SCSS for styles, single quotes in TS, 2-space indent
- All visuals hand-drawn SVG, colored by tokens — no external assets
- No backend wired yet — `auth.service.ts` and `workspace.store.ts` contain mocks

## Backend (`backend/`)

### Quick Commands

```sh
cd backend
pip install -r requirements.txt    # or: poetry install
xcli manager start --reload        # dev server on :8000
xcli health                        # check services
xcli plugin list                   # list plugins
make ci-local                      # full CI pipeline (lint + test + security + build)
make lint-fix                      # isort + black + autoflake + flake8
make test                          # pytest tests/
```

### Key Conventions

- Python 3.14 (see `.python-version`)
- xcore plugin framework: plugins in `app/` (chat, rag, xauth, xpulses), extensions in `extensions/`
- Config: `integration.yaml` (dev), `integration.docker.yaml` (prod)
- SQLite for DB, Redis for worker/pubsub — `.env` required for non-default services
- Lint: black + isort + flake8 on `xcore/` directory
- Tests: `poetry run pytest tests/` — `STRICT=1` fails on test errors, `STRICT=0` warns
- MCP servers in `mcp/` and `mcp_servers/` — word/excel/pdf via McpBridgeService

### Environment Setup

```sh
cp backend/.env.example backend/.env   # required — never commit .env
```

## Pitfalls

- **Frontend**: Don't use Tailwind spacing tokens for container widths — use named utilities (`max-w-page`, etc.)
- **Frontend**: Template classes can't contradict directives — variations go through directive inputs
- **Backend**: Embed provider/model/dim must match between API and worker (vector dimension is frozen in vec0)
- **Backend**: `xcli` is the CLI, not `python -m` directly for most operations

## Testing

- Frontend: `npm test` (vitest) — run from `frontend/`
- Backend: `make test` or `poetry run pytest tests/` — run from `backend/`
- Backend coverage: `make test-cov`
- CI targets: `make ci-lint`, `make ci-test`, `make ci-security`

## Language

Code, comments, and READMEs are in **French**. Keep all prose in French when editing.
