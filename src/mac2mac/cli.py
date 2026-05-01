import asyncio
import sys

from mac2mac.daemon import run as daemon_run
from mac2mac.protocol import Envelope
from mac2mac.transport import DEFAULT_SOCKET, send

USAGE = "usage: mac2mac {serve|say MESSAGE}"


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(USAGE)
        return 1

    cmd = argv[0]

    if cmd == "serve":
        print(f"[mac2mac] serving on {DEFAULT_SOCKET}")
        try:
            daemon_run()
        except KeyboardInterrupt:
            print("\n[mac2mac] stopped")
        return 0

    if cmd == "say":
        if len(argv) < 2:
            print("usage: mac2mac say MESSAGE")
            return 1
        message = " ".join(argv[1:])
        env = Envelope(type="say", content=message, conv_id="c-test", from_="cli")
        reply_raw = asyncio.run(send(DEFAULT_SOCKET, env.to_json()))
        reply = Envelope.from_json(reply_raw)
        print(f"[mac2mac] reply: {reply.content}")
        return 0

    print(f"unknown command: {cmd}")
    print(USAGE)
    return 1
