#!/usr/bin/env bash
# Runner script to start main.py with the workspace virtual environment
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
    VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"
elif [ -f "$SCRIPT_DIR/../venv/bin/python" ]; then
    VENV_PYTHON="$SCRIPT_DIR/../venv/bin/python"
else
    VENV_PYTHON="python3"
fi

echo "🚀 Starting Commitment Radar Bot using venv: $VENV_PYTHON"
cd "$SCRIPT_DIR"
exec "$VENV_PYTHON" main.py "$@"
