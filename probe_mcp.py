#!/usr/bin/env python3
import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / '.venv' / 'bin' / 'python'

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ModuleNotFoundError:
    # Allow ./probe_mcp.py from the shell even when /usr/bin/env python3 is not
    # the project venv. Re-exec once into the local venv where MCP is installed.
    if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
        os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])
    raise

PY = str(VENV_PY)
SERVER = str(ROOT / 'memorycore' / '__main__.py')
PRODUCTION_DB = str(ROOT / 'memory.sqlite3')


async def main() -> None:
    parser = argparse.ArgumentParser(description='Protocol-level MCP probe for MemoryCore')
    parser.add_argument('--production', action='store_true', help='write the probe record to the production memory.sqlite3 DB')
    parser.add_argument('--db', default='', help='explicit probe DB path; defaults to a temporary DB unless --production is set')
    args = parser.parse_args()

    if args.db:
        db = args.db
        cleanup_dir = None
    elif args.production:
        db = PRODUCTION_DB
        cleanup_dir = None
    else:
        cleanup_dir = tempfile.TemporaryDirectory(prefix='memorycore-probe-')
        db = str(Path(cleanup_dir.name) / 'memory.sqlite3')

    env = {**os.environ, 'LOCAL_MEMORY_DB': db}
    params = StdioServerParameters(command=PY, args=[SERVER, 'serve', '--port', '0'], env=env)
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print('DB', db)
                print('TOOLS', [t.name for t in tools.tools])
                add = await session.call_tool('memory_add', {
                    'type': 'timeline_event',
                    'title': 'MemoryCore protocol probe',
                    'content': '协议级 probe 已通过 stdio MCP 调用写入。',
                    'tags': ['probe', 'mcp'],
                    'importance': 0.6,
                })
                print('ADD', add.content[0].text[:240])
                search = await session.call_tool('memory_search', {'query': 'protocol probe', 'limit': 3})
                print('SEARCH', search.content[0].text[:500])
                ctx = await session.call_tool('memory_context', {'task': '验证多 agent 共享记忆 MCP v0', 'token_budget': 600})
                print('CONTEXT', ctx.content[0].text[:800])
                timeline = await session.call_tool('memory_timeline', {'query': 'probe', 'limit': 5})
                print('TIMELINE', timeline.content[0].text[:500])
    finally:
        if cleanup_dir is not None:
            cleanup_dir.cleanup()


asyncio.run(main())
