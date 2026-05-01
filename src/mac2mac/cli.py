"""mac2mac CLI — thin shell over `mac2mac.core`.

Subcommands:
  send <message> [--to PEER] [--conv-id ID]   send English to a peer; print reply
  end <conv_id> [--reason TEXT]                structurally end a conversation
  peers                                        list configured peers
  mcp                                          run the MCP server (stdio mode)

The MCP server (`mcp_server.py`) is a separate shell that calls the same core.
"""

from __future__ import annotations

import argparse
import sys

from mac2mac import core


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mac2mac")
    sub = parser.add_subparsers(dest="cmd", required=True)

    send_p = sub.add_parser("send", help="send English to a peer; print reply")
    send_p.add_argument("message")
    send_p.add_argument("--to", default="self", help="peer identifier (default: self)")
    send_p.add_argument("--conv-id", default=None, dest="conv_id")

    end_p = sub.add_parser("end", help="structurally end a conversation")
    end_p.add_argument("conv_id")
    end_p.add_argument("--reason", default="")

    sub.add_parser("peers", help="list configured peers")

    sub.add_parser("mcp", help="run the MCP server (stdio mode)")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "send":
        print(core.say_to_peer(args.message, args.to, args.conv_id))
        return 0

    if args.cmd == "end":
        print(core.end_conversation(args.conv_id, args.reason))
        return 0

    if args.cmd == "peers":
        for p in core.list_peers():
            print(p)
        return 0

    if args.cmd == "mcp":
        from mac2mac.mcp_server import run as mcp_run

        mcp_run()
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
