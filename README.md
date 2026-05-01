# mac2mac

> Two Macs, two agents, one conversation.

mac2mac is a peer-to-peer agent-to-agent channel between two macOS hosts. Each host runs a daemon hosting a `claude-agent-sdk` agent. The daemons connect over a Tailscale-authenticated WebSocket and the two agents **converse in plain English**.

Either Mac can speak first. Either Mac can end the conversation. Neither Mac runs commands on behalf of the other — the peer's agent decides what to do, scoped by the peer's own tool permissions.

**Status:** pre-implementation spec. See [`docs/SPEC.md`](docs/SPEC.md) for the full protocol, [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md) for the v0.1 build sequence and acceptance test, and [`lighthouse/AUTONOMY.md`](lighthouse/AUTONOMY.md) for settled design decisions.

---

## What it is

```
   Mac A's agent ──► "what's the deal with the build server?"  ──► Mac B's agent
                                                                       │
                                                                       │ (checks logs, runs tests, thinks)
                                                                       ▼
   Mac A's agent ◄── "build server is fine; flaky test is in test_x.py:14" ◄── Mac B's agent
        │
        │ (decides what to do with that info)
        ▼
       human
```

The wire payload is plain English text. There is no command schema, no RPC. From each agent's POV, the other Mac just looks like an interesting human user living on a different machine.

## What it isn't

- Not SSH-with-an-LLM. The peer agent has full agency; it isn't running your commands.
- Not a controller/worker dispatcher. The two agents are peers; either can initiate.
- Not a streaming-output relay. It's a conversation, not a pipe.

## Why

So that one Mac can ask another Mac to do agent-y things — investigate, build, report, decide — without the human at either keyboard having to context-switch between machines. The agents handle the cross-machine coordination; the humans stay in their own local conversation with their own agent.

## Design pillars

1. **Peer-to-peer.** No central gateway. Two daemons, one socket between them.
2. **English over the wire.** No typed RPC payloads. The agents interpret.
3. **Tool-driven sending.** Agents decide explicitly when to speak across the wire (via the `say_to_peer` tool). Internal monologue stays local.
4. **Tailscale for identity, bearer token for defense in depth.** Tailscale authenticates the device; the token authenticates the request.
5. **Receiver-side permissions.** What the peer's agent can do is determined by the peer's own `.claude/settings.json`. The originator cannot override.
6. **Structural goodbyes.** `end_conversation` is a separate tool from `say_to_peer`. End envelopes never become user-turns on the other side, so a "bye" exchange terminates cleanly without infinite recursion.

## How a conversation ends

Either agent can call `end_conversation(reason)`. The other side's daemon receives the close signal but does NOT inject the reason as a user-turn — it only notifies the agent informationally. The peer's agent may optionally call `end_conversation` itself as acknowledgement, but doesn't have to. After that, the conversation is closed; no further messages are accepted on that conversation ID.

This is the structural answer to "what stops two agents from infinitely replying to each other?"

```
A.agent: end_conversation("bye")     →  wire  →  B notified (no turn).
B.agent: end_conversation("bye!")    ←  wire  ←  A notified (no turn).
A.agent: (nothing — there's nothing to respond to)
```

Daemon-level safety nets back this up: turn budget (default 50 turns/conversation), idle timeout (default 10 min), and a 30s cap on `CLOSING` state.

See [`docs/SPEC.md` §6](docs/SPEC.md#6-conversation-lifecycle--termination) for the full state machine.

## Pairing UX

Both Macs in the same Tailscale tailnet:

```
$ mac2mac init                                # Mac A — first run
generated identity. listening on tailnet:9442.

$ mac2mac pair                                # Mac A
discovering peers in tailnet...
  [1] mac-b.tailnet.ts.net (running mac2mac, fingerprint b7c2...)
  [2] mac-mini-spare.tailnet.ts.net (not running mac2mac)
pair with [1] mac-b? [Y/n] y
pairing request sent. confirm on the other Mac.

$ mac2mac pair --accept mac-a.tailnet.ts.net  # Mac B
incoming pair request from mac-a (fingerprint a3f1...). accept? [Y/n] y
paired with mac-a.tailnet.ts.net.
```

No QR codes, no codes typed. Tailscale already authenticated both devices when you installed it; mac2mac just records consent and exchanges a bearer token (Keychain on both sides).

Cross-tailnet pairing (collaborator's Mac, throwaway machine) uses a 6-digit short-lived PAKE code — deferred to v1.

## Requirements

- macOS 14+ on both hosts.
- Both Macs in the same Tailscale tailnet.
- Python 3.11+.
- A Claude Code subscription (or Claude Pro / Max plan) — mac2mac uses `claude-agent-sdk`, never the raw Anthropic API.

## Install (planned, not yet implemented)

```
pipx install mac2mac
mac2mac init
mac2mac pair
mac2mac start
```

The daemon registers as a `launchd` LaunchAgent so it starts on login and survives lid close + sleep.

## Project status

| Phase | Status |
|-------|--------|
| Spec | ✅ this doc + `docs/SPEC.md` |
| v0.1 — minimum viable channel (one conversation, English, end_conversation) | ⬜ not started |
| v0.2 — 24h soak, daemon stability across sleep/wake | ⬜ not started |
| v1 — cross-tailnet PAKE pairing | ⬜ deferred |
| v2 — group channels, mobile, gateway brokering | ⬜ deferred |

## Repository layout (planned)

```
mac2mac/
├── README.md              ← you are here
├── docs/
│   └── SPEC.md            ← protocol & architecture spec
├── lighthouse/
│   └── AUTONOMY.md        ← settled design decisions (lighthouse reads this)
├── pyproject.toml
├── src/mac2mac/           ← (not yet implemented)
│   ├── cli.py             ← `mac2mac` entry point
│   ├── daemon.py          ← long-running agent + WS host
│   ├── discovery.py       ← tailscale-driven peer discovery
│   ├── transport.py       ← WS server + client
│   ├── keychain.py        ← macOS `security` CLI wrapper
│   ├── protocol.py        ← envelope formats, state machine
│   └── tools/
│       ├── say_to_peer.py
│       └── end_conversation.py
└── tests/
```

## Trust model in one paragraph

mac2mac assumes both Macs share a trust domain (same tailnet = same human, or collaborating humans). Tailscale handles device authentication and confidentiality. The bearer token is the second line of defense — a non-paired device on your tailnet still cannot connect. The receiver's `.claude/settings.json` is the third line: if the peer's agent tries something destructive, the peer's permissions either reject it or prompt the human at the peer's keyboard. mac2mac itself is not the security boundary; the layered identity (Tailscale + token + permissions) is.

## License

MIT (planned).

## Built by

Eidos AGI — `eidos-agi/mac2mac`.
