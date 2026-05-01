"""mac2mac MCP server.

Loaded by Claude Code on each Mac. Exposes `say_to_peer` and `end_conversation`
tools so the local agent (Claude Code) can talk to a peer Mac's agent (also
Claude Code) over a transport-agnostic wire.

v0.0.2 — minimum viable shape. say_to_peer is a local echo. No wire layer yet.
The wire layer (Tailscale TCP, Slack, etc.) is added in subsequent commits.
"""

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

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
                            "Peer identifier. v0 supports 'self' for loopback "
                            "testing; future: 'mac://hostname.tailnet.ts.net' "
                            "or 'slack://#channel'."
                        ),
                        "default": "self",
                    },
                    "conv_id": {
                        "type": "string",
                        "description": (
                            "Conversation ID. Omit to start a new conversation; "
                            "pass an existing one to continue."
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
                "is notified but is NOT prompted to reply (does not become a "
                "user-turn on the receiving side). Use this — not "
                "say_to_peer('bye') — when you actually want to end."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "conv_id": {
                        "type": "string",
                        "description": "The conversation to close.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional human-readable parting message.",
                    },
                },
                "required": ["conv_id"],
            },
        ),
        Tool(
            name="list_peers",
            description=(
                "List configured peers and their reachability. "
                "v0: returns 'self' as the only peer."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "say_to_peer":
        message = arguments["message"]
        peer = arguments.get("peer", "self")
        if peer != "self":
            return [
                TextContent(
                    type="text",
                    text=f"error: peer '{peer}' not implemented in v0.0.2. only 'self' loopback works.",
                )
            ]
        reply = f"[mac2mac echo via self-loop] you said: {message}"
        return [TextContent(type="text", text=reply)]

    if name == "end_conversation":
        conv_id = arguments["conv_id"]
        reason = arguments.get("reason", "")
        return [
            TextContent(
                type="text",
                text=f"conversation {conv_id} closed (reason: {reason!r}). peer notified.",
            )
        ]

    if name == "list_peers":
        return [TextContent(type="text", text="self (loopback, v0.0.2 echo)")]

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
