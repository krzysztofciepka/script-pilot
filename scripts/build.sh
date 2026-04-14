#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "Installing dependencies..."
uv sync --group dev

echo "Building binary..."
uv run pyinstaller \
    --onefile \
    --name scriptpilot \
    --hidden-import textual \
    --hidden-import textual.widgets \
    --hidden-import textual.screen \
    --hidden-import textual.css \
    --hidden-import httpx \
    --hidden-import pydantic \
    --collect-data textual \
    src/scriptpilot/__main__.py

echo "Build complete: dist/scriptpilot"
ls -lh dist/scriptpilot
