"""Entry point for ``python -m memorycore``.

Delegates to memorycore.server.main() so the package works
both as ``python -m memorycore`` and ``memorycore`` CLI.
"""
from memorycore.server import main

if __name__ == "__main__":
    raise SystemExit(main())
