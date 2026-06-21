# Contributing to ArdaLink Engine

Thanks for your interest. This document explains how to propose changes.

## Code of conduct
Be respectful. Assume good faith. No harassment.

## Development setup
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv) for dependency management
- PostgreSQL 14+ for local integration tests
- Google Earth Engine service account for live satellite ingestion

```bash
git clone git@github.com:MUNENE1212/ardalink-engine.git
cd ardalink-engine
uv sync
cp .env.example .env  # fill in
```

## Workflow
1. Branch off `dev`: `git switch -c feat/<short-name>`
2. Make focused commits (Conventional Commits, see `.commitlintrc.yml`)
3. Run pre-commit hooks: `uv run pre-commit run --all-files`
4. Run the test suite: `uv run pytest`
5. Open a PR against `dev` — fill in the PR template

## Commit messages
We use [Conventional Commits](https://www.conventionalcommits.org/). Examples:
- `feat(api): add point-conditions endpoint`
- `fix(pipeline): handle missing GEE credentials gracefully`
- `docs(arch): update data-flow diagram`

## Code style
- `ruff format` + `ruff check` (line length 100)
- `mypy --strict` on `ardalink_engine/`
- Public functions carry a docstring

## Testing
- Unit tests live next to code (`test_*.py` siblings)
- Integration tests under `tests/integration/` require a live Postgres
- Contract tests against `ardalink-api` live under `tests/contract/`

## Security
Report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## Review
At least one approval from a CODEOWNER. CI must be green.