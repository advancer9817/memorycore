"""Entry point for ``python -m local_memory_mcp``.

Delegates to local_memory_mcp.server.main() so the package works
both as ``python -m local_memory_mcp`` and ``local_memory_mcp`` CLI.
"""
from local_memory_mcp.server import main

if __name__ == "__main__":
    raise SystemExit(main())
