#!/usr/bin/env bash
# Wrapper script for MCP server — ensures correct working directory.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m local_memory_mcp serve --port 8318
