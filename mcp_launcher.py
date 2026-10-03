"""Console entry point for the bundled local stdio bridge."""

import json
import sys


def main():
    if sys.argv[1:] == ["--check-runtime"]:
        from mcp.server.fastmcp import FastMCP
        from services.halocue.workspace_mcp import create_workspace_server

        assert FastMCP and create_workspace_server
        print(json.dumps({"ok": True, "transport": "stdio"}))
        return
    from services.halocue.external_agent_mcp import main as bridge_main

    bridge_main()


if __name__ == "__main__":
    main()
