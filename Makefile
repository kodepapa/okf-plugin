.DEFAULT_GOAL := help

UV ?= uv
RUN := $(UV) run --locked
DIST_DIR ?= dist

.PHONY: help sync lint format-check format typecheck test generated check pre-commit package

help: ## Show the available developer commands.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "%-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## Install the locked development environment.
	$(UV) sync --locked --extra dev

lint: ## Run Ruff lint checks.
	$(RUN) ruff check .

format-check: ## Verify Ruff formatting without changing files.
	$(RUN) ruff format --check .

format: ## Format Python sources with Ruff.
	$(RUN) ruff format .

typecheck: ## Run strict static type checking.
	$(RUN) mypy src

test: ## Run the test suite with branch coverage enforcement.
	$(RUN) pytest --cov=okfleet

generated: ## Verify duplicated Agent Skill helpers are synchronized.
	$(RUN) python tools/verify_generated.py

check: lint format-check typecheck test generated ## Run the full local quality gate.

pre-commit: ## Run every pre-commit hook against the repository.
	$(RUN) pre-commit run --all-files

package: check ## Build and verify the wheel and source distribution.
	$(UV) build --clear --out-dir $(DIST_DIR)
	$(RUN) python tools/verify_distribution.py $(DIST_DIR)
