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
    --collect-all textual \
    --hidden-import httpx \
    --hidden-import pydantic \
    --add-data src/scriptpilot/help.md:scriptpilot \
    src/scriptpilot/__main__.py

echo "Build complete: dist/scriptpilot"
ls -lh dist/scriptpilot
