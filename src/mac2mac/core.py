"""mac2mac core — the business logic.

Both `mac2mac.cli` and `mac2mac.mcp_server` are thin shells over this module.
A future Slack bot would be a third shell. Same logic, multiple surfaces.

v0.0.3 — local echo only. The wire layer (Tailscale TCP, Slack, etc.) is
plugged in here in subsequent commits, behind the same `say_to_peer` interface.
"""

from __future__ import annotations


class Peer:
    """A peer reachable over some transport. v0.0.3 only knows 'self'."""

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        if identifier == "self":
            self.transport = "loopback"
        elif identifier.startswith("mac://"):
            self.transport = "tailscale-tcp"
        elif identifier.startswith("slack://"):
            self.transport = "slack"
        else:
            self.transport = "unknown"


def say_to_peer(
    message: str,
    peer: str = "self",
    conv_id: str | None = None,
) -> str:
    """Send an English message to a peer's agent. Returns the peer's reply.

    v0.0.3 only supports peer='self' (local echo loopback). Real wire transports
    come next.
    """
    p = Peer(peer)
    if p.transport == "loopback":
        return f"[mac2mac echo via self-loop] you said: {message}"
    if p.transport in ("tailscale-tcp", "slack"):
        raise NotImplementedError(
            f"peer '{peer}' (transport '{p.transport}') not yet wired in v0.0.3"
        )
    raise ValueError(f"unknown peer identifier: {peer!r}")


def end_conversation(conv_id: str, reason: str = "") -> str:
    """Structurally end a conversation. Peer is notified, not user-turned."""
    return f"conversation {conv_id} closed (reason: {reason!r}). peer notified."


def list_peers() -> list[str]:
    """Return configured peers. v0.0.3 only has 'self'."""
    return ["self (loopback, v0.0.3 echo)"]
