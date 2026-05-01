"""Smoke test: spin up the mac2mac MCP server, list tools, call say_to_peer.

Verifies the MCP shape works before we add the wire layer.
"""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mac2mac.mcp_server"],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"tools advertised: {tool_names}")
            expected = {"say_to_peer", "end_conversation", "list_peers"}
            actual = set(tool_names)
            assert actual == expected, f"missing: {expected - actual}, extra: {actual - expected}"

            result = await session.call_tool(
                "say_to_peer",
                {"message": "hello from smoke test", "peer": "self"},
            )
            text = result.content[0].text  # type: ignore[union-attr]
            print(f"say_to_peer reply: {text}")
            assert "you said: hello from smoke test" in text

            result = await session.call_tool(
                "end_conversation",
                {"conv_id": "c-smoke", "reason": "test done"},
            )
            text = result.content[0].text  # type: ignore[union-attr]
            print(f"end_conversation reply: {text}")
            assert "c-smoke closed" in text

            result = await session.call_tool("list_peers", {})
            text = result.content[0].text  # type: ignore[union-attr]
            print(f"list_peers reply: {text}")
            assert "self" in text

            print("PASS")
            return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
