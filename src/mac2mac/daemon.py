import asyncio

from mac2mac.protocol import Envelope
from mac2mac.transport import DEFAULT_SOCKET, serve


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    line = await reader.readline()
    if not line:
        writer.close()
        return
    env = Envelope.from_json(line.decode())
    print(f"[daemon] received: type={env.type} content={env.content!r} from={env.from_!r}")

    if env.type == "say":
        reply = Envelope(
            type="say",
            content=f"you said: {env.content}",
            conv_id=env.conv_id,
            from_="daemon",
            to=env.from_,
        )
    else:
        reply = Envelope(
            type="ack",
            reason="agent_idle",
            conv_id=env.conv_id,
            from_="daemon",
            to=env.from_,
        )

    writer.write(reply.to_json().encode() + b"\n")
    await writer.drain()
    writer.close()
    await writer.wait_closed()


def run() -> None:
    asyncio.run(serve(DEFAULT_SOCKET, handle))
