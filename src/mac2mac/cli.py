"""mac2mac CLI — agent-first, thin shell over `mac2mac.core`.

Subcommands:
  send <message> [--to PEER] [--conv-id ID]
  end <conv_id> [--reason TEXT]
  peers
  mcp                                          (run the MCP server, stdio mode)

Every command supports `--json` and `--quiet` per the cli-forge Agent-First
CLI Contract. `--help` is the authoritative schema.
"""

from __future__ import annotations

import argparse
import json
import sys

from mac2mac import core, __version__


def _shared_flags() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit a single JSON object/array on stdout. Default when stdout is not a TTY.",
    )
    p.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Bare values, one per line, no decoration. For piping.",
    )
    return p


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mac2mac",
        description=(
            "Peer-to-peer agent-to-agent channel between Macs. "
            "Speaks English over the wire; runs as a CLI or as an MCP server."
        ),
    )
    parser.add_argument("--version", action="version", version=f"mac2mac {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    shared = _shared_flags()

    send_p = sub.add_parser(
        "send",
        parents=[shared],
        help="Send English to a peer; print the peer's reply.",
        description=(
            "Send a plain-English message to a peer's agent. The peer's agent "
            "receives it as a user-turn and replies. Returns the reply."
        ),
    )
    send_p.add_argument("message", help="Plain English text to send.")
    send_p.add_argument(
        "--to",
        default="self",
        metavar="PEER",
        help="Peer identifier. v0 supports 'self' (loopback). Future: 'mac://host', 'slack://#chan'. Default: self.",
    )
    send_p.add_argument(
        "--conv-id",
        default=None,
        dest="conv_id",
        metavar="ID",
        help="Conversation ID to continue. Omit to start a new conversation.",
    )

    end_p = sub.add_parser(
        "end",
        parents=[shared],
        help="Structurally end a conversation (peer is notified, not user-turned).",
        description=(
            "Close a conversation cleanly. The peer's agent is notified that "
            "the conversation has ended but is NOT prompted to reply. Use this "
            "instead of `mac2mac send 'bye'`, which would just produce another reply."
        ),
    )
    end_p.add_argument("conv_id", metavar="CONV_ID", help="Conversation to close.")
    end_p.add_argument(
        "--reason",
        default="",
        metavar="TEXT",
        help="Optional human-readable parting message (logged + shown to peer).",
    )

    sub.add_parser(
        "peers",
        parents=[shared],
        help="List configured peers and their reachability.",
        description="List all configured peers. v0 only knows 'self'.",
    )

    sub.add_parser(
        "mcp",
        help="Run the MCP server in stdio mode (loaded by Claude Code).",
        description=(
            "Run the mac2mac MCP server over stdio. This is what Claude Code "
            "invokes when the MCP is registered. Same business logic as the "
            "CLI; different surface."
        ),
    )

    return parser


def _emit(
    *,
    json_payload: object,
    plain: str,
    quiet_text: str,
    json_output: bool,
    quiet: bool,
) -> None:
    if json_output:
        print(json.dumps(json_payload, ensure_ascii=False))
    elif quiet:
        print(quiet_text)
    else:
        print(plain)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    explicit_json = getattr(args, "json_output", False)
    quiet = getattr(args, "quiet", False)
    auto_json = not sys.stdout.isatty() and args.cmd != "mcp" and not quiet
    json_output = explicit_json or auto_json

    if args.cmd == "send":
        try:
            reply = core.say_to_peer(args.message, args.to, args.conv_id)
        except NotImplementedError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        _emit(
            json_payload={"reply": reply, "peer": args.to, "conv_id": args.conv_id},
            plain=reply,
            quiet_text=reply,
            json_output=json_output,
            quiet=quiet,
        )
        return 0

    if args.cmd == "end":
        result = core.end_conversation(args.conv_id, args.reason)
        _emit(
            json_payload={
                "closed": True,
                "conv_id": args.conv_id,
                "reason": args.reason,
                "message": result,
            },
            plain=result,
            quiet_text=result,
            json_output=json_output,
            quiet=quiet,
        )
        return 0

    if args.cmd == "peers":
        peers = core.list_peers()
        _emit(
            json_payload=[
                {"id": "self", "transport": "loopback", "description": p} for p in peers
            ],
            plain="\n".join(peers),
            quiet_text="self",
            json_output=json_output,
            quiet=quiet,
        )
        return 0

    if args.cmd == "mcp":
        from mac2mac.mcp_server import run as mcp_run

        mcp_run()
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
