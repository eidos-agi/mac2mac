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

### 3.4 Token rotation

The shared bearer token `T` from §3.2 is durable but rotatable:

- **Manual rotation:** `mac2mac rotate-token <peer>` — generates a new token, writes it to local Keychain, sends a `POST /mac2mac/rotate-token` to the peer over the existing authenticated connection. Peer confirms (auto-accepts because the request is on an already-trusted channel), writes the new token to its Keychain, and replies `200`. The old token is invalidated on both sides at the moment of confirmation. Any in-flight WS connections are closed and re-established with the new token.
- **Scheduled rotation:** the daemon may rotate every N days automatically (default: never). Configurable via `~/.config/mac2mac/config.toml` setting `rotate_every_days`. Off by default because v0 doesn't need it; surface for paranoid users.
- **Emergency rotation:** if a peer's token is suspected compromised, the human runs `mac2mac unpair <peer>` then `mac2mac pair`. This forces a full re-handshake (with human confirmation on both sides) and a fresh token.

Rotation is per-peer, not global. Each pairing has its own token; rotating one doesn't affect others.

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
| `ack` | Acknowledge receipt; "I have nothing to say back" | `conv_id` (string), `reason` (enum: `done_thinking`, `no_value_to_add`, `agent_idle`, `daemon_timeout`) | **NO** — daemon-level signal only |
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
- **LLM token budget:** each `conv_id` has a max-token cost cap (default 200k input + 200k output tokens, configurable). The daemon tracks SDK usage. On exceedance, force-close with `reason: "token budget exceeded"`. Prevents pathological tool-heavy conversations from quietly burning the subscription's effective rate-limit headroom. Bounds *cost*, where turn budget bounds *count*.
- **Rate limit on `say_to_peer`:** the tool is throttled at the daemon level (default: max 6 calls/minute, max 1 call/second). Bursts beyond that fail the tool call locally with `rate_limit_exceeded` and do NOT cross the wire. Catches a degenerate agent that calls `say_to_peer` in a tight loop before the turn-budget counter even has a chance to fire.
- **Idle timeout:** if no `say` envelope flows on a `conv_id` for `idle_timeout` seconds (default 600s), the daemon force-closes. Conversation is over by inactivity.
- **Agent response timeout:** if a daemon delivers a `say` user-turn to its local agent and the agent produces no tool call (neither `say_to_peer` nor `end_conversation`) within `agent_response_timeout` seconds (default **600s** — 10 min, revised from 120s after consultation; agents doing real tool work routinely exceed 2 minutes), the daemon sends `ack` with `reason: agent_idle` to the peer.
- **Closing timeout:** in `CLOSING` state, if no peer `end` ack arrives within 30s, the daemon transitions to `CLOSED` unilaterally and logs `unilateral_close`.

These five mechanisms compose. The turn budget catches dumb-loop runaways; the token budget catches expensive-tool runaways; the rate limit catches burst runaways; the idle timeout catches abandoned conversations; the agent response timeout catches stuck local agents.

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
- The Tailscale tailnet is uncompromised at the perimeter. If a third device joins the tailnet maliciously, the bearer token is the second line of defense — a non-paired device cannot connect.
- The Keychain is intact on both sides. (Token compromise = full channel compromise.)

mac2mac does NOT assume:
- That either agent is benign. The peer's permissions (§8.1) are the boundary.
- That the network path is private end-to-end against arbitrary attackers. WSS over Tailscale's WireGuard tunnel handles confidentiality and integrity against off-tailnet attackers.

### 8.4 Threat model

| Adversary | Capability | mac2mac's defense | Residual risk |
|-----------|-----------|-------------------|---------------|
| Off-tailnet attacker | Internet-reachable; tries direct WS dial to your Tailscale IP | Daemon binds only to the Tailscale interface; off-tailnet packets never reach the listener. WSS adds confidentiality if any path is exposed. | None significant. |
| Same-tailnet device, no token | Network-reachable on the tailnet; tries WS dial | Daemon rejects with `401` on bearer-token check. No content leaks; only the listener's existence is observable. | Listener fingerprinting (low value). |
| Same-tailnet device WITH stolen token | Has `T` somehow; can authenticate as the paired peer | Daemon's connection IS authorized; attacker can read English content and inject messages. **Bearer-token compromise = full channel compromise.** | High — token theft on the local Mac is the dominant risk. Mitigations: Keychain ACL (require user auth), token rotation (§3.4), fingerprint pinning (rotation-on-reinstall is detected). |
| Compromised local agent (RCE on the Mac itself) | Arbitrary code execution on Mac A | Once Mac A is compromised, mac2mac cannot defend Mac A. But Mac B still enforces ITS OWN permissions on requests from A — agent A cannot escalate beyond what B's `.claude/settings.json` allows. | Compromised Mac can drive peer agent up to peer's permission ceiling. |
| Curious peer | Legitimately paired peer wants to learn about you | Sees only `say_to_peer` content you choose to send. Does NOT see your filesystem, env, intermediate reasoning, or other tool outputs. | None — you chose to pair with them. Privacy boundary is the `say_to_peer` tool. |
| Network observer (tailnet-internal) | Sees encrypted WireGuard traffic between paired Macs | WireGuard is point-to-point encrypted on the tailnet; observers see ciphertext. Bearer token in the WS upgrade is also inside the tunnel. | None significant for the v0 case. |
| Tailscale provider (Tailscale Inc) | Operates the coordination plane; could in theory route traffic through their servers | Tailscale's data plane is point-to-point WireGuard — they don't see content unless DERP relay is needed (NAT traversal failure). When DERP is used, content is still WireGuard-encrypted end-to-end. | Trust in Tailscale Inc as a control-plane operator. |

**Load-bearing assumption:** the per-peer bearer token is durable enough to keep secret for the peer's lifetime. Rotation (§3.4) is the compensating control if that assumption weakens. Per-session ephemeral keys are deferred to v1 — v0 leans on Keychain access controls + rotation.

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

## 11. Worked Examples

These transcripts show the protocol in operation. Each example exposes a different aspect of the design. Implementations should pass these as integration tests.

### 11.1 Happy path with structural goodbye

**Setup:** Mac A and Mac B paired. Daniel at Mac A asks his agent for help; agent A decides to consult agent B.

```
─── wire ───
A→B  {type:say,  conv_id:c-001, content:"hey, what's the status of the build server?"}
B→A  {type:say,  conv_id:c-001, content:"build is green. last failure was 3h ago — flaky test in test_pipeline.py:42, retry passed."}
A→B  {type:say,  conv_id:c-001, content:"thanks. ping me if it goes red."}
B→A  {type:say,  conv_id:c-001, content:"will do."}
A→B  {type:end,  conv_id:c-001, reason:"thx"}
B→A  {type:end,  conv_id:c-001, reason:"anytime"}

─── A's agent view ───
[user-turn from human] "is the build server ok?"
[tool] say_to_peer("hey, what's the status of the build server?", conv_id=new) → opens c-001
[user-turn from peer] "build is green. last failure was 3h ago — flaky test..."
[tool] say_to_peer("thanks. ping me if it goes red.", conv_id=c-001)
[user-turn from peer] "will do."
[tool] end_conversation(reason="thx", conv_id=c-001)
[notification — NOT a user-turn] "peer ended c-001, said 'anytime'"
[no further turns on c-001]

─── B's agent view ───
[user-turn from peer] "hey, what's the status of the build server?"
[tool] Bash("git log --oneline...") → checks
[tool] say_to_peer("build is green. last failure was 3h ago...", conv_id=c-001)
[user-turn from peer] "thanks. ping me if it goes red."
[tool] say_to_peer("will do.", conv_id=c-001)
[notification — NOT a user-turn] "peer ended c-001, said 'thx'"
[tool] end_conversation(reason="anytime", conv_id=c-001)
```

**Demonstrates:** the bye-bye invariant. A's `end_conversation` triggers a notification on B (no turn). B chooses to send its own `end_conversation` as polite ack. A receives B's ack as a notification (no turn). A's agent does not — and cannot — generate a third turn on c-001.

### 11.2 Implicit silence (pause, not close)

**Setup:** A mentions something B has no opinion on. B's agent doesn't have anything useful to add.

```
─── wire ───
A→B  {type:say,  conv_id:c-002, content:"fyi I'm going to grab lunch."}
B→A  {type:ack,  conv_id:c-002}                 ← daemon-generated; B agent didn't call say_to_peer

─── B's agent view ───
[user-turn from peer] "fyi I'm going to grab lunch."
[reasoning] "no useful response. don't call say_to_peer."
[no tool calls]
[daemon sends ack to A automatically]

─── A's agent view ───
[notification — NOT a user-turn] "peer received c-002, no reply"
[no further turns on c-002]

─── 2 hours later ───
A→B  {type:say,  conv_id:c-002, content:"back. anything change?"}
       ← A reuses c-002; conv_id is still OPEN, daemon delivers as fresh user-turn on B
```

**Demonstrates:** silence ≠ close. The conversation is paused. Either side can resume on the same `conv_id` later. Compare to 11.1 where `end` would have closed it permanently.

### 11.3 Race close (simultaneous goodbyes)

**Setup:** Both agents independently decide to wrap up at the same instant. `end` envelopes cross in flight.

```
─── wire (envelopes cross) ───
A→B  {type:end, conv_id:c-003, reason:"gotta run"}    ╲
                                                       ╳   (in flight simultaneously)
B→A  {type:end, conv_id:c-003, reason:"same, ttyl"}   ╱

─── A's daemon ───
[state: OPEN] agent calls end_conversation → state: CLOSING → send end
[receives end from B while in CLOSING] → state: CLOSED
[notify agent: "peer also ended c-003, said 'same, ttyl'"]

─── B's daemon ───
[state: OPEN] agent calls end_conversation → state: CLOSING → send end
[receives end from A while in CLOSING] → state: CLOSED
[notify agent: "peer also ended c-003, said 'gotta run'"]
```

**Demonstrates:** idempotency. The `CLOSING → CLOSED` transition is the same whether you reach it via your own `end` followed by peer's ack, or via simultaneous `end`s. Each agent gets exactly one notification. No extra turns. No protocol error.

### 11.4 Runaway prevention (turn budget hits)

**Setup:** Two agents in a degenerate loop ("interesting!" / "yes, very!" / "indeed!"). Neither calls `end_conversation`. Daemon enforces.

```
─── wire (turns 1..49) ───
A→B  {type:say, conv_id:c-004, content:"interesting!"}
B→A  {type:say, conv_id:c-004, content:"yes, very!"}
... 47 more turns ...

─── turn 50 (default budget) ───
A→B  {type:say, conv_id:c-004, content:"definitely!"}
[A's daemon increments turn_count to 50, hits budget]
[A's daemon force-sends end on its own initiative]
A→B  {type:end, conv_id:c-004, reason:"turn budget exceeded (50)"}
A→A  [internal] notify A's agent: "c-004 force-closed by daemon: turn budget"

─── B's side ───
B receives the say (turn 50), processes, attempts say_to_peer
B receives the end immediately after
B's daemon: state c-004 is now CLOSED
B's daemon rejects the in-flight say_to_peer call with error "conversation closed"
B's agent gets notification: "peer ended c-004 (turn budget exceeded)"
```

**Demonstrates:** the daemon is the safety net. Agents can't be trusted to recognize they're stuck. The turn budget is a hard ceiling that fires regardless of agent reasoning. The `reason` field is human-debuggable.

### 11.5 Wrong tool: `say_to_peer("bye")` does NOT end

**Setup:** Agent A reasons "time to wrap up" and calls `say_to_peer("bye")` instead of `end_conversation("bye")`. The conversation does NOT close.

```
─── wire ───
A→B  {type:say, conv_id:c-005, content:"bye"}    ← still a regular message!
B→A  {type:say, conv_id:c-005, content:"oh ok, talk later. did you want me to push the branch first?"}
                                                  ← B treats "bye" as conversation content, replies normally
A→B  {type:say, conv_id:c-005, content:"oh — yes please"}
... conversation continues ...
```

**Demonstrates:** the structural distinction matters. The English content `"bye"` carries human meaning, but the protocol only recognizes the envelope `type`. If the agent wants to actually end, it must call `end_conversation`. The system prompt for each agent must make this clear.

This is also why mac2mac does not try to detect goodbyes from content — that would be a heuristic with edge cases. The agent declares its intent structurally.

### 11.6 Pairing handshake (first-run UX)

**Setup:** Daniel runs `mac2mac init` on Mac A and Mac B for the first time, then `mac2mac pair` on each.

```
─── Mac A ───
$ mac2mac init
✓ generated identity (fingerprint a3f1c92b...)
✓ saved to keychain (com.eidosagi.mac2mac.identity)
✓ listening on tailnet:9442

$ mac2mac pair
discovering peers in tailnet...
  [1] mac-mini.tailnet.ts.net   running mac2mac (fingerprint b7c2...)
  [2] iphone-15.tailnet.ts.net  not running mac2mac
pair with [1] mac-mini? [Y/n] y
✓ pairing request sent. confirm on the other Mac.

─── Mac B ───
$ mac2mac init
✓ generated identity (fingerprint b7c29e8a...)
✓ listening on tailnet:9442

$ mac2mac pair
incoming pair request from mac-a.tailnet.ts.net (fingerprint a3f1c92b...)
  accept? [Y/n] y
✓ shared token generated, saved to keychain on both sides
✓ paired with mac-a.tailnet.ts.net

─── back on Mac A ───
✓ confirmed by peer
✓ paired with mac-mini.tailnet.ts.net
```

**Demonstrates:** zero codes typed. Tailscale already authenticated both devices when Daniel installed it. mac2mac just records consent and exchanges a bearer token. Note that fingerprints are displayed at confirmation time so a human can sanity-check (matches displayed fingerprint vs expected).

---

## 12. Future Work (deferred from v0)

- **Cross-tailnet pairing** — 6-digit PAKE pairing code (v1).
- **More than 2 peers** — group channels (v2). Will require routing decisions and N-way termination semantics.
- **Mobile clients** — phone-as-pair (v2). QR codes become useful here.
- **Optional always-on gateway** — for cases where a worker Mac is laptop-only and sleeps too much (v2). Wire protocol stays the same; gateway just brokers.
- **Conversation transcripts as durable artifacts** — write completed conversations to the cockpit's `briefs/` for review (v1).
- **Multiple agents per Mac** — currently one agent per daemon per Mac. v2 may add per-conversation agent identities.

---

## 13. Open questions (decide before v0.1 ships)

1. ~~**Default `agent_response_timeout`?**~~ **RESOLVED.** Set to 600s (10 min). 120s was too short for any agent doing real tool work. See §6.2.
2. ~~**Should `say_to_peer` block until peer responds, or return immediately?**~~ **RESOLVED.** v0 blocks. Returns when peer's daemon either delivers an `ack` (peer didn't reply) or a `say` (peer replied) or `end` (peer closed). Non-blocking variants deferred to v1 if multi-conversation becomes a real use case.
3. ~~**Should the daemon expose conversation transcripts to the human?**~~ **RESOLVED.** Yes — `mac2mac log <conv_id>` reads the daemon log and reconstructs the conversation. v0.1 must include this; debugging without it would be miserable.
4. **How does the human "join" or "interrupt" a conversation?** v0: they don't. They talk to their local agent normally; their agent decides whether to relay. Future `mac2mac inject <conv_id> "<message>"` would queue a string as a user-turn into the local agent's context — at which point the agent may or may not call `say_to_peer`. Defer to v1.
5. ~~**What happens if the agent tries to `say_to_peer` while already in a `CLOSING` state for that `conv_id`?**~~ **RESOLVED.** Daemon returns tool error `conversation_closing` (and `conversation_closed` once `CLOSED`). Agent must use a new `conv_id` to start fresh. Documented in §6.3.
6. **(NEW) Default LLM token budget per `conv_id`?** Tentatively 200k input + 200k output. Needs validation against typical Claude Agent SDK conversation costs. Probably fine for v0; revisit after first soak.
7. **(NEW) Multi-agent-per-daemon — wire-protocol future-proofing.** Should v0 envelopes include an optional `to_agent` and `from_agent` field (defaulting to a single implicit agent) so v2 group/multi-agent doesn't require a breaking schema change? Recommended: yes. Cost is 2 ignored fields in v0.
8. **(NEW) On reconnect, can `OPEN` conversations resume, or are they always closed?** v0 says always closed for simplicity. Revisit after soak — if humans habitually sleep mid-conversation and want resumption, add seq-numbered envelope replay (each side keeps last-N envelopes per `conv_id` and replays unacked ones on reconnect).

---

## 14. Spec change log

| Date | Change | Driver |
|------|--------|--------|
| 2026-05-01 | Initial spec | Design conversation. |
| 2026-05-01 | Worked examples added (§11). | Stress-test the protocol against happy path + bye-bye + race + runaway + wrong-tool + pairing scenarios. |
| 2026-05-01 | LLM token budget added to safety nets (§6.2). `ack` envelope gained `reason` enum. Rate limit on `say_to_peer` added. `agent_response_timeout` revised to 600s. | Cept consultation flagged these as gaps. |
| 2026-05-01 | Token rotation procedure (§3.4) added. Threat model (§8.4) added with adversary table. | Cept consultation flagged "no rotation mechanism" and "trust model is one paragraph." |
| 2026-05-01 | Open questions §13 reorganized — 4 of 5 resolved, 3 new ones added (token budget, multi-agent future-proofing, reconnect resume). | After incorporating cept feedback. |
