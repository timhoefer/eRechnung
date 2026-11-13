"""Probe the packaged bridge, without an app connection, credentials or real data."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def check(binary):
    params = StdioServerParameters(command=str(Path(binary).resolve()), args=["--mcp"],
                                  env={"ERECHNUNG_MCP_TOKEN": "", "ERECHNUNG_MCP_URL": "", "ERECHNUNG_MCP_ENDPOINT_FILE": "",
                                       "ERECHNUNG_TEST_MODE": "1", "ERECHNUNG_MCP_AUTOSTART": "0"})
    async with Client(params, read_timeout_seconds=20) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        assert {"create_invoice", "delete_invoice", "request_status", "list_issuers"} <= tools
        assert "approve" not in tools
        refused = await client.call_tool("list_issuers", {})
        assert refused.is_error and not refused.structured_content["ok"]
    print("Bundled MCP discovery and disabled-access check passed.")


def check_app_start(command, *, browser=None):
    """Start the real entrypoint with only a new, disposable test data directory."""
    with tempfile.TemporaryDirectory(prefix="erechnung-mcp-start-") as directory:
        env = {k: v for k, v in os.environ.items() if not k.startswith("ERECHNUNG_MCP_")}
        env.update(ERECHNUNG_TEST_MODE="1", ERECHNUNG_MCP="1", TMPDIR=directory,
                   PYINSTALLER_RESET_ENVIRONMENT="1", FLASK_DEBUG="0")
        if browser:
            env["BROWSER"] = browser
        with tempfile.TemporaryFile() as log:
            child = subprocess.Popen([*command, "--mcp-start"], env=env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=log, start_new_session=True)
            try:
                deadline = time.monotonic() + 30
                opener = build_opener(ProxyHandler({}))
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        log.seek(0)
                        raise AssertionError("App startup failed: " + log.read(4000).decode(errors="replace"))
                    endpoints = list(Path(directory).glob("erechnung-selftest-*/mcp-endpoint.json"))
                    if endpoints:
                        url = json.loads(endpoints[0].read_text())["url"]
                        try:
                            with opener.open(url + "/agents/status", timeout=1) as response:
                                assert json.load(response) == {"service": "eRechnung", "mcp_enabled": True}
                            with opener.open(url + "/agents", timeout=1) as response:
                                assert b'name="consent"' in response.read()
                            req = Request(url + "/agents/call", data=b'{"tool":"list_issuers","arguments":{}}',
                                headers={"Content-Type": "application/json", "Authorization": "Bearer " + "x" * 43})
                            try:
                                opener.open(req, timeout=1)
                            except HTTPError as exc:
                                assert exc.code == 403
                            else:
                                raise AssertionError("Starting the app must not grant access.")
                            assert not (endpoints[0].parent / "agent_access.json").exists()
                            return
                        except URLError as exc:
                            if isinstance(exc, HTTPError):
                                raise
                    time.sleep(0.1)
                raise AssertionError("App did not become ready in time.")
            finally:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)


if __name__ == "__main__":
    # build_macos.sh publishes the ZIP/DMG and removes its temporary app bundle.
    # Probe the actual ZIP payload, not an app left over from an earlier build.
    with tempfile.TemporaryDirectory(prefix="erechnung-mcp-bundle-") as directory:
        subprocess.run(["ditto", "-x", "-k", str(Path(sys.argv[1]).resolve()), directory], check=True)
        binary = Path(directory) / "eRechnung.app/Contents/MacOS/eRechnung"
        asyncio.run(check(binary))
        check_app_start([str(binary)])
        print("Bundled app startup and unchanged opt-in check passed.")
