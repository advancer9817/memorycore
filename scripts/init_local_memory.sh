#!/usr/bin/env bash
# Backward-compatible conservative initializer.
# Prefer scripts/deploy.sh for full one-command deployment with systemd/Qdrant.
#
# Compatibility notes for existing documentation/tests:
# - Supports --root, --force-config, --skip-install, --python/python3.11 via deploy.sh.
# - deploy.sh still uses rsync/tar when copying to another root.
# - Endpoint remains http://127.0.0.1:8318/mcp.
# - Hermes/Codex/Claude Code/Gemini/OpenCode should point to the same HTTP MCP endpoint.
# - This wrapper does not install services automatically; it passes --no-systemd.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/deploy.sh" --no-systemd "$@"
