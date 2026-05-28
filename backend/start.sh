#!/usr/bin/env bash
# Start the NexusIQ FastAPI backend (Ollama multi-agent service)
# Run from the project root: bash backend/start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Activate venv if present
if [[ -f ".venv/bin/activate" ]]; then
  source .venv/bin/activate
fi

echo "Starting NexusIQ Ollama backend on http://0.0.0.0:8000 …"
exec python -m uvicorn backend.main:app \
  --host "${BACKEND_HOST:-0.0.0.0}" \
  --port "${BACKEND_PORT:-8000}" \
  --reload \
  --log-level "${LOG_LEVEL:-info}"
