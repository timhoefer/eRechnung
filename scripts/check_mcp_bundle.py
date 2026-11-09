"""Probe the packaged bridge, without an app connection, credentials or real data."""
import asyncio
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def check(binary):
    params = StdioServerParameters(command=str(Path(binary).resolve()), args=["--mcp"],
                                  env={"ERECHNUNG_MCP_TOKEN": "", "ERECHNUNG_MCP_URL": "", "ERECHNUNG_MCP_ENDPOINT_FILE": ""})
    async with Client(params, read_timeout_seconds=20) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        assert {"create_invoice", "delete_invoice", "request_status", "list_issuers"} <= tools
        assert "approve" not in tools
        refused = await client.call_tool("list_issuers", {})
        assert refused.is_error and not refused.structured_content["ok"]
    print("Bundled MCP discovery and disabled-access check passed.")


if __name__ == "__main__":
    asyncio.run(check(sys.argv[1]))
