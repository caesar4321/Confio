# Repository Guidelines

For project context, architecture, and scope, always start with the root [README.md](README.md) in the `/Confio` directory.

## Project Structure & Module Organization
- Backend: Django project in `config/`, apps in `apps/` and feature folders (e.g., `payments/`, `notifications/`, `telegram_verification/`). Entry points: `manage.py`, `config/asgi.py`.
- GraphQL: Schema in `schema.graphql`.
- Mobile: React Native app via `package.json`, sources under RN defaults; iOS files in `ios/`.
- Blockchain & services: `blockchain/`, `contracts/`, `prover/`, `prover-service/`.
- Assets & templates: `static/`, `staticfiles/`, `templates/`.
- Ops: `Makefile`, `Dockerfile`, `scripts/`, `nginx*/`, `supervisor/`, `cloud-init.yml`.
- Docs & examples: `docs/`, `README.md`, `.env.example`.
- Tests: Python tests live at repo root as `test_*.py` files.

## Build, Test, and Development Commands
- Python setup: `make install` (installs into `./myvenv`).
- Run (ASGI, hot reload): `make runserver-dev` or production-like: `make runserver`.
- DB: `make migrate`, `make makemigrations`, optional bootstrap: `make db-setup`.
- Collect static: `make collectstatic`. Clean caches: `make clean`.
- Tests (Django): `make test`.
- Mobile (from repo root): `npm install`, `npm run ios|android`, Metro: `npm start`, JS tests: `npm test`.

## Coding Style & Naming Conventions
- Python: PEP 8, 4-space indents, `snake_case` for modules/functions, `PascalCase` for classes, type hints where sensible. Keep Django apps small and cohesive under `apps/`.
- JavaScript/TypeScript: `camelCase` for variables/functions, `PascalCase` for React components. Run `npm run lint` and `prettier` before committing.
- Files: tests mirror subject names, e.g., `payments/` code covered by `test_payments_*.py`.

## Testing Guidelines
- Python: Use Django’s test runner (`make test`). Prefer `TestCase` with fast, isolated tests. Add fixtures under app folders when needed. Aim for meaningful coverage on business logic and GraphQL resolvers.
- JS: Use Jest (`npm test`) for unit/UI snapshot tests. Keep RN tests deterministic.

## Commit & Pull Request Guidelines
- Commits: Use Conventional Commits where possible (`feat:`, `fix:`, `docs:`). Imperative mood, scoped changes.
- PRs: Clear description, link issues, outline migration or env changes, include test evidence (logs, screenshots for UI), and steps to verify. Keep PRs small and focused.

## Security & Configuration Tips
- Secrets: Never commit real keys. Use `.env` and follow `.env.example`. Validate config with `check_env.py` when available.
- Database: Local Postgres via `make db-setup`. For resets, use `make db-reset` (destructive).
