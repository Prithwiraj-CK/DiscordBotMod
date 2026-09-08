#!/bin/zsh
set -euo pipefail

PROJECT_DIR="/Users/prithiraj/DiscordBotMod"
cd "$PROJECT_DIR"

if [[ ! -f .env ]]; then
  print -u2 "Missing $PROJECT_DIR/.env"
  exit 1
fi

set -a
source .env
set +a

# The supervisor is for local shadow operation only.
export SHADOW_MODE=true
exec "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/bot.py"
