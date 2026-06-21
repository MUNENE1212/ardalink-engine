# 08 — Team

[← Runbooks](07-RUNBOOKS.md) · [Back to Executive Index](00-EXECUTIVE-INDEX.md)

## Onboarding (engine)

1. Read [Executive Index](00-EXECUTIVE-INDEX.md) (5 min)
2. Read [Architecture](01-ARCHITECTURE.md) (10 min)
3. Run `uv sync` and `pytest` locally
4. Open a PR against `dev` with a doc fix or test (good-first-issue)

## Standards

- Python 3.12, `uv` for deps
- `ruff format` + `ruff check` (line 100)
- `mypy --strict`
- Pytest, coverage floor 70% enforced in CI
- Conventional Commits (commitlint)

## On-call rotation

Documented in `docs/07-RUNBOOKS.md`.

## Code review

- One CODEOWNER approval required
- CI green is non-negotiable
- Prefer small PRs (< 400 lines)