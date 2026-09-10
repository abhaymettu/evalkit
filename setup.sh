#!/usr/bin/env bash
# Creates .venv, installs evalkit and its pinned deps, runs the tests. Safe to rerun.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt -e .
.venv/bin/python -m pytest -q
echo
echo "Usage: .venv/bin/evalkit run examples/suite.jsonl --mock --out results/run1.jsonl"
echo "       .venv/bin/evalkit report results/run1.jsonl"
echo "       .venv/bin/evalkit diff results/run1.jsonl results/run2.jsonl"
