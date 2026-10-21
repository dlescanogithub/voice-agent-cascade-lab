PYTHON ?= python3

.PHONY: setup lint format typecheck test eval eval-voice eval-regression demo secretscan secretscan-hash ci

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

eval-voice:
	$(PYTHON) -m voice_cascade eval-voice

eval-regression:
	$(PYTHON) -m voice_cascade eval-regression

eval-regression-turn:
	@set +e; $(PYTHON) -m voice_cascade eval-regression --turn-taking; code=$$?; set -e; \
	if [ $$code -eq 0 ]; then echo "expected turn-taking regression to fail"; exit 1; fi; \
	echo "turn-taking regression failed as required (exit $$code)"

eval-regression-webhook:
	@set +e; $(PYTHON) -m voice_cascade eval-regression --webhook; code=$$?; set -e; \
	if [ $$code -eq 0 ]; then echo "expected webhook regression to fail"; exit 1; fi; \
	echo "webhook regression failed as required (exit $$code)"

demo:
	$(PYTHON) -m voice_cascade demo

secretscan:
	$(PYTHON) -m voice_cascade secretscan .

secretscan-hash:
	$(PYTHON) -c "import hashlib,re; from pathlib import Path; text=Path('docs/PROVENANCE.md').read_text(); expected=re.search(r'sha256:\\s*([0-9a-f]{64})', text).group(1); actual=hashlib.sha256(Path('src/voice_cascade/secretscan.py').read_bytes()).hexdigest(); assert actual==expected, actual; print(actual)"

ci: lint typecheck test eval secretscan secretscan-hash eval-regression-turn eval-regression-webhook
	@set +e; $(PYTHON) -m voice_cascade eval-regression; code=$$?; set -e; \
	if [ $$code -eq 0 ]; then echo "expected eval-regression to fail"; exit 1; fi; \
	echo "eval-regression failed as required (exit $$code)"
