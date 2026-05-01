"""mac2mac MCP server — thin shell over `mac2mac.core`.

Loaded by Claude Code on each Mac. Exposes `say_to_peer`, `end_conversation`,
and `list_peers` as MCP tools. All real logic lives in `mac2mac.core`; this
module only translates between MCP's typed tool API and core's plain functions.
"""

from __future__ import annotations

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mac2mac import core

server: Server = Server("mac2mac")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="say_to_peer",
            description=(
                "Send an English message to a peer's Claude Code agent. "
                "The peer may be another Mac (mac://host), a Slack channel "
                "(slack://#channel), or another transport. Returns the peer's "
                "reply as a string. Use this when you want the OTHER agent to "
                "do something, not when you want to end the conversation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Plain English text to send to the peer.",
                    },
                    "peer": {
                        "type": "string",
                        "description": (
                            "Peer identifier. v0 supports 'self' for loopback; "
                            "future: 'mac://hostname.tailnet.ts.net' or "
                            "'slack://#channel'."
                        ),
                        "default": "self",
                    },
                    "conv_id": {
                        "type": "string",
                        "description": (
                            "Conversation ID. Omit to start new; pass existing "
                            "to continue."
                        ),
                    },
                },
                "required": ["message"],
            },
        ),
        Tool(
            name="end_conversation",
            description=(
                "Structurally end a conversation with a peer. The peer's agent "
                "is notified but is NOT prompted to reply. Use this — not "
                "say_to_peer('bye') — when you actually want to end."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "conv_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["conv_id"],
            },
        ),
        Tool(
            name="list_peers",
            description="List configured peers and their reachability.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "say_to_peer":
        text = core.say_to_peer(
            message=arguments["message"],
            peer=arguments.get("peer", "self"),
            conv_id=arguments.get("conv_id"),
        )
        return [TextContent(type="text", text=text)]

    if name == "end_conversation":
        text = core.end_conversation(
            conv_id=arguments["conv_id"],
            reason=arguments.get("reason", ""),
        )
        return [TextContent(type="text", text=text)]

    if name == "list_peers":
        text = "\n".join(core.list_peers())
        return [TextContent(type="text", text=text)]

    raise ValueError(f"unknown tool: {name}")


async def _serve() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def run() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    run()
