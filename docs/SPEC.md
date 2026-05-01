# mac2mac — Protocol & Architecture Specification

**Status:** v0 design, pre-implementation. Authoritative for v0.1 build.
**Last updated:** 2026-05-01.
**Related:** `lighthouse/AUTONOMY.md` (settled decisions).

---

## 1. Overview

mac2mac is a **peer-to-peer agent-to-agent channel** between two macOS hosts. Each host runs a daemon. Each daemon hosts a `claude-agent-sdk` agent. The two daemons connect over a Tailscale-authenticated WebSocket and the two agents **converse in plain English**.

The wire payload is plain text. There is no command schema, no RPC syntax, no typed actions. From each agent's point of view, the other host appears as an unusually capable human user who happens to live on a different machine.

The human at either keyboard can talk to their local agent normally. The local agent decides — by calling a single tool, `say_to_peer` — when something is worth sending across the wire. The other agent's daemon receives the message and feeds it to its agent as a user-turn. The cycle continues until one side calls `end_conversation` or the daemon enforces a safety stop.

mac2mac is **not**:
- a remote command executor (it is not SSH-with-an-LLM)
- a controller/worker dispatcher (the agents are peers)
- a streaming-output relay (it is not a pipe)
- an RPC framework (the wire is English, not typed payloads)

---

## 2. Architecture

```
   ┌─────────────── Mac A ───────────────┐         ┌─────────────── Mac B ───────────────┐
   │                                     │         │                                     │
   │   human-A ───► local I/O ───►       │         │       ◄─── local I/O ◄─── human-B   │
   │                                     │         │                                     │
   │           ┌─────────────────┐       │         │       ┌─────────────────┐           │
   │           │  agent (SDK)    │       │         │       │  agent (SDK)    │           │
   │           │  - tools        │       │         │       │  - tools        │           │
   │           │  - say_to_peer  │       │         │       │  - say_to_peer  │           │
   │           │  - end_convo    │       │         │       │  - end_convo    │           │
   │           └────────┬────────┘       │         │       └────────┬────────┘           │
   │                    │                │         │                │                    │
   │           ┌────────▼────────┐       │         │       ┌────────▼────────┐           │
   │           │   daemon        │ ◄─────┼ WS over ┼─────► │   daemon        │           │
   │           │   - keychain    │       │ tailnet │       │   - keychain    │           │
   │           │   - discovery   │       │ +bearer │       │   - discovery   │           │
   │           │   - protocol    │       │ token   │       │   - protocol    │           │
   │           └─────────────────┘       │         │       └─────────────────┘           │
   └─────────────────────────────────────┘         └─────────────────────────────────────┘
```

Both daemons are functionally symmetric. Either side can initiate a conversation; either side can end it.

---

## 3. Discovery & Pairing

### 3.1 First-time pairing UX (v0)

Both Macs are already in the same Tailscale tailnet. The daemon listens on a known port (`9442/tcp` over Tailscale) and exposes a `GET /mac2mac/identity` endpoint returning a self-advertisement:

```json
{
  "version": "0.1.0",
  "hostname": "mac-a.tailnet.ts.net",
  "fingerprint": "sha256:a3f1...",
  "paired_peers": ["mac-b.tailnet.ts.net"]
}
```

The pairing flow:

```
$ mac2mac init                              # Mac A, first run
generated identity. fingerprint: a3f1...
saved to keychain (com.eidosagi.mac2mac.identity).
listening on tailnet:9442.

$ mac2mac pair                              # Mac A
discovering peers in tailnet...
  [1] mac-b.tailnet.ts.net (running mac2mac, fingerprint b7c2...)
  [2] mac-mini-spare.tailnet.ts.net (not running mac2mac)
pair with [1] mac-b? [Y/n] y
pairing request sent. confirm on the other Mac.

$ mac2mac pair --accept mac-a.tailnet.ts.net  # Mac B confirms
incoming pair request from mac-a (fingerprint a3f1...). accept? [Y/n] y
shared token generated. saved to keychain on both sides.
paired with mac-a.tailnet.ts.net.
```

### 3.2 Pairing handshake (cryptographic)

1. A's daemon generates a fresh random token `T` (256 bits, urandom).
2. A sends `POST /mac2mac/pair` to B with `{from: A, token: T, fingerprint_a: <hash of A's identity>}` over the Tailscale-authenticated channel.
3. B's daemon prompts the human at B for confirmation.
4. On confirmation, B writes `T` to its Keychain under `com.eidosagi.mac2mac.peer.<A.hostname>`.
5. B replies `200 OK` with `{fingerprint_b: <hash of B's identity>}`.
6. A writes `T` to its Keychain under `com.eidosagi.mac2mac.peer.<B.hostname>`.

After this, both sides have:
- The peer's Tailscale hostname.
- A shared bearer token `T`.
- The peer's identity fingerprint (for detecting key-rotation / impersonation).

### 3.3 Re-pairing & revocation

- `mac2mac unpair <peer>` — deletes the keychain entry for that peer on the local side. The other side will get a `401` on next connection attempt and should also unpair locally.
- If a peer's fingerprint changes (e.g., reinstall), the local daemon refuses to connect and logs a fingerprint-mismatch event. The human must re-run `mac2mac pair`.

### 3.4 Cross-tailnet pairing (deferred to v1)

For Macs not in the same tailnet, a 6-digit short-lived PAKE pairing code replaces auto-discovery. Out of scope for v0.

---

## 4. Transport

### 4.1 Connection

After pairing, either daemon can dial the other:

```
WSS ws://<peer.tailnet.ts.net>:9442/mac2mac/channel
Authorization: Bearer <T>
X-Mac2Mac-From: <self.tailnet.ts.net>
X-Mac2Mac-Fingerprint: <self.fingerprint>
```

The receiving daemon validates:
1. Connection originates from a Tailscale interface (refuses non-tailnet peers with `403`).
2. Bearer token matches the keychain entry for the claimed `From` host.
3. Fingerprint matches the recorded fingerprint for that peer.

If any check fails, the connection is rejected with structured error and the failure is logged.

### 4.2 Keepalive

Either side sends a `{type: "ping"}` every 30 seconds. Missing 3 consecutive pings closes the connection. The dialing side reconnects with exponential backoff (1s, 2s, 4s, ..., capped at 60s). All in-flight conversations on a closed connection are marked `interrupted` (see §6).

### 4.3 Listener binding

Daemons bind only to the Tailscale interface, never to `0.0.0.0`. The address is resolved at startup via `tailscale ip -4`. If Tailscale is not running, the daemon refuses to start and logs an error.

---

## 5. Wire Protocol

All envelopes are JSON, one envelope per WS frame.

### 5.1 Envelope types

| `type` | Purpose | Body fields | User-turn injected? |
|--------|---------|-------------|---------------------|
| `say` | Send English content to peer's agent | `content` (string), `conv_id` (string) | **YES** — receiving daemon injects `content` as user-turn |
| `end` | End a conversation | `reason` (optional string), `conv_id` (string) | **NO** — receiving daemon notifies agent only |
| `ack` | Acknowledge receipt; "I have nothing to say back" | `conv_id` (string) | **NO** — daemon-level signal only |
| `ping` | Keepalive | none | **NO** |
| `pong` | Keepalive response | none | **NO** |
| `error` | Protocol-level error | `code`, `message` | **NO** |

### 5.2 Common header fields

Every envelope includes:

```json
{
  "type": "...",
  "from": "mac-a.tailnet.ts.net",
  "ts": "2026-05-01T14:23:01.234Z",
  "msg_id": "uuid-v4",
  ...type-specific body...
}
```

### 5.3 Conversation IDs

Every `say` and `end` envelope carries a `conv_id`. A new `conv_id` (one not seen before by the receiving daemon) opens a new conversation. The same `conv_id` continues an existing one. Daemons keep a per-`conv_id` state machine (see §6).

A conversation can be:
- Started by either side (whoever calls `say_to_peer` first with a fresh `conv_id`).
- Ended by either side (whoever calls `end_conversation` first; the other side acknowledges).

---

## 6. Conversation Lifecycle & Termination

This is the section that prevents two agents from recursing on each other's user-turns forever.

### 6.1 State machine (per `conv_id`)

```
                  say (new conv_id)
                  ──────────────►
            ┌──────────────────────┐
            │                       │
   ┌──────► │   OPEN                │ ◄────── ack (no reply)
   │        │   (turns flow both    │
   │  say   │    ways)              │ ──────► (waits for new say)
   │        │                       │
   └──────  └──┬──────────────────┬─┘
                │                  │
                │ end              │ end (race-cross)
                ▼                  ▼
      ┌──────────────┐    ┌──────────────┐
      │ CLOSING      │    │ CLOSED       │
      │ (waiting for │    │ (no further  │
      │  peer's ack  │    │  envelopes   │
      │  end)        │    │  accepted)   │
      └──────┬───────┘    └──────────────┘
             │
             │ peer end OR timeout (30s)
             ▼
      ┌──────────────┐
      │ CLOSED       │
      └──────────────┘
```

### 6.2 The four termination mechanisms

**1. Implicit silence (pause, not close).**
When a daemon delivers a `say` to its local agent and the agent's response does NOT call `say_to_peer`, the daemon sends an `ack` envelope. The conversation stays in `OPEN` but with no in-flight messages. Either side can resume later by calling `say_to_peer` on the same `conv_id`. This is "I have nothing to say right now," not "we're done."

**2. Explicit goodbye (`end_conversation` tool).**
When the agent calls `end_conversation(reason)`, the daemon sends an `end` envelope. The conversation moves to `CLOSING`. The peer's daemon receives the `end`, moves the conversation to `CLOSED` on its side, and **notifies its agent without injecting a user-turn**: "Peer ended conversation `conv_id`. Their parting message was: 'bye'." The agent may optionally call `end_conversation` itself in response, which sends a reciprocal `end`. The originator's daemon receives this and confirms `CLOSED`.

**3. The bye-bye invariant.**
`end` envelopes never become user-turns on the receiving side. This is the structural guarantee that answers the question "if A says bye and B says bye back, A doesn't respond." Once A's `end_conversation` is called, A's daemon will not inject any subsequent envelope from B as a user-turn for that `conv_id`. B's reciprocal `end` is delivered to A's agent only as a notification, not a turn.

**4. Daemon-level safety net.**
- **Turn budget:** each `conv_id` has a max turn count (default 50, configurable). The daemon counts turns on both sides; once exceeded, the daemon force-closes by sending `end` with `reason: "turn budget exceeded"`. This catches runaway loops where neither agent decides to stop.
- **Idle timeout:** if no `say` envelope flows on a `conv_id` for `idle_timeout` seconds (default 600s), the daemon force-closes. Conversation is over by inactivity.
- **Closing timeout:** in `CLOSING` state, if no peer `end` ack arrives within 30s, the daemon transitions to `CLOSED` unilaterally and logs `unilateral_close`.

### 6.3 Edge cases

| Scenario | Behavior |
|----------|----------|
| Both agents call `end` simultaneously (envelopes cross in flight) | Each daemon sees `end` from peer while in `CLOSING`. Both transition to `CLOSED`. Each agent gets one notification: "peer ended." Idempotent. |
| Agent calls `say_to_peer` after `end_conversation` on same `conv_id` | Daemon refuses (returns tool error). Conversation is `CLOSED` locally. Agent must use a new `conv_id` to start a fresh conversation. |
| Peer sends `say` on a `conv_id` we have marked `CLOSED` | Daemon drops the envelope, replies with `error: closed`. Logged. |
| Peer offline during `end_conversation` | A's daemon enters `CLOSING`, waits 30s for ack, then unilaterally `CLOSED`. A's agent is notified `peer offline`. |
| Connection drops mid-conversation | All `OPEN` conversations transition to `interrupted` state. On reconnect, daemons can resume them (peers compare `conv_id`s and seq numbers). v0 may simply mark them `CLOSED` for simplicity. |
| Agent never calls any tool after receiving `say` | Daemon waits `agent_response_timeout` (default 120s), then sends `ack` to peer indicating "no reply." Peer's agent is notified. |

### 6.4 What the agent's system prompt must say

Each agent's system prompt includes:

> You can talk to your peer Mac by calling `say_to_peer(message, conv_id)`. Your peer's agent will see your message as a user-turn and may respond.
>
> When you want to end the conversation, call `end_conversation(reason, conv_id)` instead of saying "bye" via `say_to_peer`. The `end_conversation` tool is a structural close — the other side will be notified that the conversation ended but won't be prompted to reply. If you say "bye" via `say_to_peer`, your peer will treat it as a normal message and likely respond.
>
> If you receive a notification that your peer ended the conversation, you may optionally call `end_conversation` yourself to acknowledge politely — but you don't have to. After `end_conversation` is called on a `conv_id`, that conversation is closed and you cannot send more messages on it.
>
> If you have nothing useful to say in response to a peer's message, just don't call `say_to_peer`. The conversation will pause; either side can resume later.

---

## 7. Agent Tools

The daemon exposes the following tools to its local agent via `claude-agent-sdk`'s tool API. These are the **only** tools that mac2mac itself adds; all other tools come from the agent's normal toolkit (the agent's `.claude/settings.json` permissions).

### 7.1 `say_to_peer`

```python
def say_to_peer(message: str, conv_id: str | None = None) -> dict:
    """Send an English message to the peer Mac's agent.

    Args:
        message: Plain English text to send.
        conv_id: Optional. If omitted, opens a new conversation.
                 If provided, continues an existing OPEN conversation.

    Returns:
        {"conv_id": str, "delivered": bool, "peer_responded": bool}

    The peer agent will receive `message` as a user-turn. The peer may
    respond, in which case you'll receive their response as your next
    user-turn. The peer may also choose not to respond (silence).
    """
```

### 7.2 `end_conversation`

```python
def end_conversation(reason: str = "", conv_id: str = ...) -> dict:
    """Structurally end a conversation with the peer.

    The peer's daemon will be notified that this conversation is closed,
    but will NOT inject `reason` as a user-turn. The peer's agent gets
    an informational notification only and is not expected to respond.
    The peer may optionally send back its own end_conversation as
    acknowledgement; you will be notified but not user-turned on it.

    Use this when you actually want to end the conversation. Saying
    "bye" via say_to_peer does NOT end the conversation — the peer will
    just receive "bye" as a normal message and probably reply.

    Args:
        reason: Optional human-readable parting message (logged, shown
                to peer's agent as notification).
        conv_id: The conversation to close. Required.

    Returns:
        {"closed": True, "peer_acknowledged": bool}
    """
```

### 7.3 `list_conversations`

```python
def list_conversations() -> list[dict]:
    """List active and recent conversations with the peer.

    Returns:
        [{"conv_id": str, "state": "OPEN"|"CLOSING"|"CLOSED",
          "last_activity": iso8601, "turn_count": int, "peer": str}, ...]
    """
```

---

## 8. Permissions & Trust

### 8.1 Receiver-side scoping

The peer's agent operates with **the peer's own permissions**. Every tool call the peer makes is gated by the peer's `~/.claude/settings.json`. The originating agent has zero ability to escalate the peer's permissions or bypass any guardrails on the peer's machine.

This is the load-bearing safety property. If Mac A's agent says "delete everything in your home directory," Mac B's agent will attempt to call its `Bash` tool, and Mac B's permissions will either reject it (`deny: ["Bash(rm:*)"]`) or prompt the human at Mac B for confirmation. Mac A cannot override that.

### 8.2 What the originator sees

The originator only sees what the peer's agent chooses to communicate back via `say_to_peer`. The originator does NOT see:
- The peer's tool-call traces (unless the peer chooses to summarize them).
- The peer's intermediate reasoning.
- The peer's filesystem, environment variables, or any other state.

This preserves privacy on the peer side and prevents originator-side log analysis from discovering peer secrets.

### 8.3 Trust model

mac2mac assumes:
- Both Macs are owned by the same human (or by collaborating humans who trust each other) — same-tailnet means same trust domain.
- The Tailscale tailnet is uncompromised. If a third device joins the tailnet maliciously, the bearer token is the second line of defense — a non-paired device cannot connect.
- The Keychain is intact on both sides. (Token compromise = full channel compromise.)

mac2mac does NOT assume:
- That either agent is benign. The peer's permissions are the boundary.
- That the network path is private end-to-end. WSS over Tailscale's WireGuard tunnel handles confidentiality and integrity.

---

## 9. Logging & Observability

Every daemon writes structured JSON to `~/Library/Logs/mac2mac/daemon.log`:

```json
{"ts": "...", "level": "info", "event": "conversation.opened", "conv_id": "...", "peer": "..."}
{"ts": "...", "level": "info", "event": "envelope.received", "type": "say", "conv_id": "...", "msg_id": "...", "from": "..."}
{"ts": "...", "level": "info", "event": "envelope.sent", "type": "say", "conv_id": "...", "msg_id": "..."}
{"ts": "...", "level": "warn", "event": "fingerprint.mismatch", "peer": "...", "expected": "...", "received": "..."}
{"ts": "...", "level": "info", "event": "conversation.closed", "conv_id": "...", "reason": "...", "by": "self"|"peer"|"timeout"}
```

`mac2mac status` reads the log and shows a live conversation list, peer connection state, and recent events.

---

## 10. Failure Modes (catalog)

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Tailscale not running | Daemon refuses to start | Human starts Tailscale, restarts daemon |
| Peer Mac asleep | Connection refused / WS dial timeout | Daemon retries with backoff. v0 returns "peer offline" tool error to caller. |
| Peer daemon crashed | WS disconnect | Daemon retries with backoff. In-flight conversations marked `CLOSED`. |
| Bearer token mismatch | `401` on WS upgrade | Connection refused. Logged. Human must `mac2mac unpair` and re-pair. |
| Fingerprint mismatch | Identity check at handshake | Connection refused. Logged. Human must investigate (key rotation? compromise?) before re-pairing. |
| Lid close mid-conversation | Pings stop, WS times out | All `OPEN` conversations marked `CLOSED`. On wake, daemon reconnects but conversations are gone. |
| Both sides try to pair simultaneously | Double-pair race | One side's `POST /pair` wins, the other gets `409`. Idempotent. |
| Agent emits malformed tool call | SDK rejects locally | Tool error returned to agent. No envelope sent. Agent retries or gives up. |
| Conversation runaway (50+ turns) | Daemon turn-budget counter | Daemon force-closes with `end (reason: "turn budget")`. Both agents notified. |
| Both agents deadlock waiting | Idle timeout | Daemon force-closes with `end (reason: "idle timeout")`. |

---

## 11. Future Work (deferred from v0)

- **Cross-tailnet pairing** — 6-digit PAKE pairing code (v1).
- **More than 2 peers** — group channels (v2). Will require routing decisions and N-way termination semantics.
- **Mobile clients** — phone-as-pair (v2). QR codes become useful here.
- **Optional always-on gateway** — for cases where a worker Mac is laptop-only and sleeps too much (v2). Wire protocol stays the same; gateway just brokers.
- **Conversation transcripts as durable artifacts** — write completed conversations to the cockpit's `briefs/` for review (v1).
- **Multiple agents per Mac** — currently one agent per daemon per Mac. v2 may add per-conversation agent identities.

---

## 12. Open questions (decide before v0.1 ships)

1. **Default `agent_response_timeout`?** Currently 120s. Too short for any agent that does real work. Probably 10 minutes is more honest.
2. **Should `say_to_peer` block until peer responds, or return immediately?** Blocking is simpler for the agent's reasoning; non-blocking enables parallel conversations. v0: block. Revisit if multi-conversation becomes a thing.
3. **Should the daemon expose conversation transcripts to the human?** A `mac2mac log <conv_id>` command would be useful for debugging. Yes — write this. Cheap.
4. **How does the human "join" or "interrupt" a conversation?** v0: they don't. They talk to their local agent normally; their agent decides whether to relay. v1: maybe a `mac2mac inject <conv_id> "<message>"` for direct injection.
5. **What happens if the agent tries to `say_to_peer` while already in a `CLOSING` state for that `conv_id`?** Daemon should reject with a clear error. Confirm in implementation.
