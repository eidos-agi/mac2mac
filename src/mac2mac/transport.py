import asyncio
from pathlib import Path

DEFAULT_SOCKET = Path.home() / "Library" / "Application Support" / "mac2mac" / "sock"


async def serve(socket_path: Path, handler) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()
    server = await asyncio.start_unix_server(handler, str(socket_path))
    async with server:
        await server.serve_forever()


async def send(socket_path: Path, envelope_json: str) -> str:
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write(envelope_json.encode() + b"\n")
    await writer.drain()
    response = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return response.decode().strip()
