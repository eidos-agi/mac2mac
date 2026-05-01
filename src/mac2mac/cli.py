"""mac2mac CLI.

The CLI is intentionally thin in v0 — the real work happens inside the MCP
server (`mac2mac-mcp`), which Claude Code loads on each Mac.

`mac2mac mcp` runs the MCP server in stdio mode (what Claude Code invokes).
"""

import sys

from mac2mac.mcp_server import run as mcp_run

USAGE = "usage: mac2mac mcp"


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(USAGE)
        return 1

    cmd = argv[0]

    if cmd == "mcp":
        mcp_run()
        return 0

    print(f"unknown command: {cmd}")
    print(USAGE)
    return 1
