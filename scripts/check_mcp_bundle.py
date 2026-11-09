"""Probe the packaged bridge, without an app connection, credentials or real data."""
import asyncio
import subprocess
import sys
import tempfile
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
    # build_macos.sh publishes the ZIP/DMG and removes its temporary app bundle.
    # Probe the actual ZIP payload, not an app left over from an earlier build.
    with tempfile.TemporaryDirectory(prefix="erechnung-mcp-bundle-") as directory:
        subprocess.run(["ditto", "-x", "-k", str(Path(sys.argv[1]).resolve()), directory], check=True)
        asyncio.run(check(Path(directory) / "eRechnung.app/Contents/MacOS/eRechnung"))
