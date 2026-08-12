PYTHON := uv run python

.PHONY: install test lint format typecheck check build clean

install:
	uv sync --dev

test:
	uv run pytest

lint:
	uv run ruff check src tests --fix

fix:
	uv run ruff check src tests --fix
	uv run ruff format src tests

typecheck:
	uv run mypy src

check: lint typecheck test

build:
	uv build

clean:
	rm -rf build dist
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete