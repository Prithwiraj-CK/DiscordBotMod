#!/bin/zsh
# Run the real Luna evaluation before loading a new local shadow deployment.
# A failed case keeps the currently running service untouched.
set -euo pipefail

task_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$task_root"

env PYTHONPYCACHEPREFIX=/tmp/salena-pycache .venv/bin/python evaluate.py --run-openai --min-score 1.0
launchctl kickstart -k "gui/$(id -u)/com.discordbotmod.shadow"
