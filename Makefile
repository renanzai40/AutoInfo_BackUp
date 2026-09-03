.PHONY: install dev-install test lint clean stripe-mock backup validate

install:
	pip install -e .

dev-install:
	# For full coverage (pytest-cov + the optional deps the HAVE_* gates in
	# tests/conftest.py guard): pip install -e ".[dev,stripe,pdf,tts,web,video]"
	# Note: stripe is a core dependency (always pulled in); web/pdf/tts/video are
	# extras and ffmpeg must be on PATH separately. `pip install -e ".[all]"` also works.
	pip install -e ".[dev]"

test:
	# Full suite (~3000 tests) can exceed 10 minutes: the single slowest test
	# is test_backward_compat.py::TestAllV01TestsPass (nested subprocess re-run
	# of 10 v0.1 test files, ~114s, marked "slow"). pytest-timeout (180s per
	# test, pyproject.toml) bounds every test so a hang fails fast with a clear
	# timeout message. Targeted runs are unaffected, e.g.:
	#   pytest tests/test_cli_commands.py        # single file
	#   pytest -m "not slow"                     # full suite minus nested re-run
	pytest -v

test-coverage:
	# Requires pytest-cov (in the dev extra). Run with optional extras installed
	# (see dev-install) for full coverage of the HAVE_*-gated modules.
	pytest --cov=autoinfo --cov-report=term-missing

lint:
	ruff check src/ tests/
	mypy src/

lint-fix:
	ruff check --fix src/ tests/

clean:
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .ruff_cache/ .mypy_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

stripe-mock:
	docker compose up -d stripe-mock

backup:
	bash scripts/backup-db.sh

# One-command quality adjudication (issue #194 spec B).  L0 dead-code gate
# runs by default (blocking); the L1 semantic battery is opt-in with
# --semantic (calls the configured LLM; see scripts/agent_review/battery.py).
# Usage: make validate DIR=outputs/<domain>   (default DIR=outputs)
validate:
	python3 scripts/quality_gate.py $(DIR) || exit 1
	@echo "L0 gate passed for $(DIR) — optional L1 semantic battery:"
	@echo "  python3 scripts/agent_review/battery.py $(DIR)              # worklist preview"
	@echo "  python3 scripts/agent_review/battery.py $(DIR) --semantic   # + LLM verdicts"
