.DEFAULT_GOAL := help
.PHONY: help install fmt lint typecheck test cov parity check fixtures up demo down clean

PARITY_ENV := .parity
PY := core server sdk demo

help: ## List targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-10s %s\n", $$1, $$2}'

install: ## Install the workspace and dev tools
	uv sync

fmt: ## Format code
	uv run ruff format $(PY)
	uv run ruff check --fix $(PY)

lint: ## Lint without changing files
	uv run ruff format --check $(PY)
	uv run ruff check $(PY)

typecheck: ## Strict mypy on every package
	uv run mypy

test: ## Run all tests (server tests need SENTINEL_TEST_DATABASE_URL / _REDIS_URL, else skip)
	uv run pytest

cov: ## Tests with a coverage report
	uv run pytest --cov --cov-report=term-missing

parity: ## Compare against Evidently and NannyML in a separate environment
	uv venv --python 3.12 $(PARITY_ENV)
	uv pip install --python $(PARITY_ENV) -e ./core pytest hypothesis evidently nannyml "pandas<3"
	NML_DISABLE_USAGE_LOGGING=1 $(PARITY_ENV)/bin/python -m pytest core/tests/parity \
		-p no:cacheprovider --import-mode=importlib

fixtures: ## Rebuild the dashboard demo data from the engine
	uv run python demo/build_fixtures.py --out web/public/data

up: ## Run the stack in Docker: dashboard on http://localhost:8080
	docker compose up -d --build --wait

demo: ## Stream the demo scenarios into the running stack
	docker compose --profile demo run --rm --build demo

down: ## Stop the stack (data volumes are kept)
	docker compose down

check: lint typecheck cov ## Everything CI runs except parity and the Docker stack

clean: ## Remove caches and build output
	rm -rf .coverage coverage.xml .mypy_cache .ruff_cache $(PARITY_ENV) dist build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
