"""MCP server — exposes the six polilabs primitives as MCP tools over stdio.

Lets any MCP-compatible client query the corpus.

Configure in your MCP client with something like:

    {
      "mcpServers": {
        "polilabs": {
          "command": "/path/to/polilabs/.venv/bin/python",
          "args": ["/path/to/polilabs/mcp_server.py"],
          "env": {
            "POLILABS_DB": "/path/to/polilabs/data/polilabs.db"
          }
        }
      }
    }

Note: this server does not require ANTHROPIC_API_KEY — it only reads from
data/polilabs.db. Build the DB first with `python scripts/build_index.py`.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Make `import agent` / `import api` resolve when the server is launched directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from agent.tools import (
    TOOL_DESCRIPTIONS,
    TOOL_FUNCTIONS,
    TOOL_SCHEMAS,
)

app: Server = Server("polilabs")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Return the six polilabs primitives as MCP tools."""
    return [
        Tool(
            name=name,
            description=TOOL_DESCRIPTIONS[name],
            inputSchema=TOOL_SCHEMAS[name],
        )
        for name in TOOL_FUNCTIONS
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch to the matching tool implementation. All tools return a JSON string."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return [TextContent(type="text", text=f'{{"error": "unknown tool: {name}"}}')]
    result = fn(**(arguments or {}))
    return [TextContent(type="text", text=result)]


async def _main() -> None:
    db = Path(os.environ.get("POLILABS_DB", "data/polilabs.db"))
    if not db.exists():
        print(
            f"[polilabs-mcp] polilabs.db not found at {db}; "
            "build it with `python scripts/build_index.py`",
            file=sys.stderr,
        )
        sys.exit(1)
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
