# NeuraLink Copilot — Makefile (README §10).
# On Windows without `make`, run the equivalent CLI directly, e.g.:
#   .venv\Scripts\python -m neuralink.cli demo
# (or use ./tasks.ps1 <target>).

PYTHON ?= python
CLI := $(PYTHON) -m neuralink.cli

.DEFAULT_GOAL := help
.PHONY: help setup prep seed train index run-sim run demo serve \
        verify-airgap verify-audit test lint typecheck lock clean

help:  ## list targets
	@echo "NeuraLink Copilot targets:"
	@echo "  setup          create venv + install (uv)"
	@echo "  prep           seed + train + index (offline-prep, deterministic)"
	@echo "  seed           generate synthetic runbooks + incidents"
	@echo "  train          train IsolationForest baseline"
	@echo "  index          embed corpus -> encrypted FAISS/numpy index"
	@echo "  run-sim        stream simulated telemetry (cpu_starvation)"
	@echo "  run            launch the Textual operator terminal (PRIMARY UI)"
	@echo "  demo           full end-to-end scenario (headline)"
	@echo "  serve          run the localhost FastAPI server"
	@echo "  verify-airgap  static scan for forbidden network symbols"
	@echo "  verify-audit   verify the tamper-evident audit chain"
	@echo "  test/lint/typecheck   dev checks"

setup:  ## create venv and install (core + dev). Optional extras: llm, faiss, embed, web
	uv venv .venv
	uv pip install --python .venv -e ".[dev]"
	@echo "Activate: .venv\\Scripts\\activate (Windows) or source .venv/bin/activate"

prep: seed train index  ## one-shot offline preparation

seed:
	$(CLI) seed

train:
	$(CLI) train

index:
	$(CLI) index

run-sim:
	$(CLI) run-sim --scenario cpu_starvation

run:
	$(CLI) tui --scenario cpu_starvation --seed 42

demo:
	$(CLI) demo --scenario cpu_starvation --seed 42

serve:
	$(CLI) serve

verify-airgap:
	$(CLI) verify-airgap

verify-audit:
	$(CLI) verify-audit

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check src scripts tests

typecheck:
	$(PYTHON) -m mypy

lock:  ## pin the current environment for reproducible air-gapping
	uv pip freeze --python .venv > requirements.lock

clean:
	$(PYTHON) -c "import shutil,glob,os; [shutil.rmtree(p,ignore_errors=True) for p in glob.glob('**/__pycache__',recursive=True)]"
