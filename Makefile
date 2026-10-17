PYTHON ?= python3

.PHONY: setup lint format typecheck test eval eval-regression demo secretscan ci

setup:
	$(PYTHON) -m pip install -e ".[dev]"
	$(PYTHON) -m pre_commit install || true

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest

eval:
	$(PYTHON) -m voice_cascade eval

eval-regression:
	$(PYTHON) -m voice_cascade eval-regression

demo:
	$(PYTHON) -m voice_cascade demo

secretscan:
	$(PYTHON) -m voice_cascade secretscan .

ci: lint typecheck test eval secretscan
	@set +e; $(PYTHON) -m voice_cascade eval-regression; code=$$?; set -e; \
	if [ $$code -eq 0 ]; then echo "expected eval-regression to fail"; exit 1; fi; \
	echo "eval-regression failed as required (exit $$code)"
