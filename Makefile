.PHONY: install format lint typecheck security test test-security test-chaos test-perf check sbom build clean

install:
	uv sync --all-extras

format:
	uv run black src tests
	uv run ruff check src tests --fix

lint:
	uv run ruff check src tests
	uv run black --check src tests

typecheck:
	uv run mypy

security:
	uv run bandit -q -r src -c pyproject.toml

test:
	uv run pytest

test-security:
	uv run pytest -m security --no-cov

test-chaos:
	uv run pytest -m chaos --no-cov

test-perf:
	uv run pytest -m performance --no-cov

check: lint typecheck security test

sbom:
	syft dir:. -o cyclonedx-json=sbom.cdx.json

build:
	uv build

clean:
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml sbom.cdx.json
