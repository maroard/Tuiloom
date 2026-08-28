PYTHON := uv run python

.PHONY: install test lint format-check typecheck check fix build clean

install:
	uv sync --dev

test:
	uv run pytest --cov=tuiloom --cov-report=term-missing

lint:
	uv run ruff check src tests

format-check:
	uv run ruff format --check src tests

fix:
	uv run ruff check src tests --fix
	uv run ruff format src tests

typecheck:
	uv run mypy src tests

check: lint format-check typecheck test

build:
	uv build
	uv run twine check dist/*

clean:
	rm -rf build dist
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
