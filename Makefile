.PHONY: dev lint lint-fix format type-check test test-fast test-live arch check hooks

dev:
	uv sync --all-groups
	uv run pre-commit install --install-hooks

lint:
	uv run ruff check src scripts tests

lint-fix:
	uv run ruff check --fix src scripts tests

format:
	uv run ruff format src scripts tests

type-check:
	uv run ty check src

test:
	uv run pytest tests --cov=src --cov-report=term-missing --cov-fail-under=80 -q

test-fast:
	uv run pytest tests -q

test-live:
	uv run pytest tests/test_live_game.py -m live -q

arch:
	uv run scripts/arch_guard.py; uv run pytest tests/test_cleanliness.py -q

check: format lint type-check arch test-fast

hooks:
	uv run pre-commit run --all-files
