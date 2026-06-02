OpenMemory UI fork notice

This directory vendors and adapts the OpenMemory UI from the Mem0 repository.

- Upstream repository: https://github.com/mem0ai/mem0
- Upstream path: openmemory/ui
- Baseline commit: a3154d59e52386d4e1189c1f5f44819868f76514
- Fork date: 2026-06-01
- Upstream license: Apache License 2.0
- Included license file: ui/LICENSE

Local changes:

- API calls are adapted to local-memory-mcp's `/api/v1/*` compatibility layer.
- The UI remains a client of mcore SQLite/Qdrant APIs; it does not import or run the Mem0 backend SDK.
