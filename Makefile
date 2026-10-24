.DEFAULT_GOAL := help
.PHONY: help install fmt lint typecheck test cov parity check clean

PARITY_ENV := .parity

help: ## List targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-10s %s\n", $$1, $$2}'

install: ## Install the workspace and dev tools
	uv sync

fmt: ## Format code
	uv run ruff format core
	uv run ruff check --fix core

lint: ## Lint without changing files
	uv run ruff format --check core
	uv run ruff check core

typecheck: ## Strict mypy on the library
	uv run mypy

test: ## Run unit and property tests
	uv run pytest

cov: ## Tests with a coverage report
	uv run pytest --cov --cov-report=term-missing

parity: ## Compare against Evidently and NannyML in a separate environment
	uv venv --python 3.12 $(PARITY_ENV)
	uv pip install --python $(PARITY_ENV) -e ./core pytest hypothesis evidently nannyml "pandas<3"
	NML_DISABLE_USAGE_LOGGING=1 $(PARITY_ENV)/bin/python -m pytest core/tests/parity \
		-p no:cacheprovider --import-mode=importlib

check: lint typecheck cov ## Everything CI runs except parity

clean: ## Remove caches and build output
	rm -rf .coverage coverage.xml .mypy_cache .ruff_cache $(PARITY_ENV) dist build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
