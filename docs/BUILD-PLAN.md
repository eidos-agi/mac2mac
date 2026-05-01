# mac2mac — Build Plan (v0.1)

**Status:** pre-implementation. Authoritative build sequence for the v0.1 artifact.
**Companion to:** `docs/SPEC.md` (the full spec) and `lighthouse/AUTONOMY.md` (settled decisions).

This document collapses the spec to its smallest buildable surface and lays out the order of work. Anything in SPEC.md NOT listed here as "v0.1 in scope" is deferred. The point of this doc is to make it impossible to over-build.

---

## 1. The v0.1 acceptance test

**v0.1 ships when this scenario passes end-to-end on two real Macs:**

> Daniel runs `mac2mac init` on Mac A and Mac B. Runs `mac2mac pair` on each, accepting the discovered peer. Runs `mac2mac start` on each. Then types into Mac A's terminal: *"ask my other Mac to tell me its hostname."* The agent on Mac A calls `say_to_peer`, the agent on Mac B receives the message, runs `hostname`, and `say_to_peer`s the result back. Agent A relays the answer to Daniel. Daniel says "thanks bye" — agent A calls `end_conversation`. Agent B is notified, optionally calls `end_conversation` itself, and the conversation closes cleanly. No hung process, no orphaned conversation, no infinite loop.

That's it. One conversation, one tool call across the wire, one clean structural close. Everything below exists to make that scenario work.

---

## 2. v0.1 surface — what's actually in scope

### In scope

| Component | Minimum behavior | SPEC ref |
|-----------|-----------------|----------|
| `mac2mac init` | Generate identity (keypair fingerprint), store in Keychain, print self-info | §3.1 |
| `mac2mac pair` (initiator) | List peers via Tailscale, send `POST /mac2mac/pair`, wait for confirmation | §3.1, §3.2 |
| `mac2mac pair` (acceptor) | Receive incoming pair request, prompt human for `[Y/n]`, exchange token | §3.2 |
| `mac2mac start` | Start daemon: bind WS server on tailnet:9442, dial paired peers, register agent tools, run claude-agent-sdk loop | §2, §4 |
| Discovery | Probe known port on each tailnet peer (single-shot at `pair` time) | §3.1 |
| WS transport | Tailscale-only bind, bearer-token auth, JSON envelopes one-per-frame | §4 |
| Envelopes | `say`, `end`, `ack`, `ping`, `pong`, `error` (full v0 schema) | §5.1 |
| Conversation state machine | OPEN → CLOSING → CLOSED with the bye-bye invariant | §6.1, §6.2 |
| Safety nets | Turn budget (50), idle timeout (600s), agent response timeout (600s), closing timeout (30s) | §6.2 |
| Agent tools | `say_to_peer`, `end_conversation`, `list_conversations` | §7 |
| Logging | Structured JSON to `~/Library/Logs/mac2mac/daemon.log` | §9 |
| `mac2mac log <conv_id>` | Read log, reconstruct conversation transcript | §13 (Q3 resolved) |

### Out of scope for v0.1 (deferred to later v0.X or v1)

| Deferred | Reason |
|---------|--------|
| `mac2mac unpair`, `mac2mac rotate-token` | Pairing works in v0.1; rotation can wait. |
| LLM token budget safety net | Turn budget is enough to prove the loop-prevention pattern works. Add token budget in v0.2 once costs measurable. |
| Rate limit on `say_to_peer` | Same — turn budget covers the v0.1 happy path. |
| `ack.reason` enum richness | v0.1 ships a single `agent_idle` reason. Other enum values are wire-compatible additions. |
| `launchd` LaunchAgent / auto-start | v0.1 = manual `mac2mac start`. v0.2 = launchd. |
| Sleep/wake reconnect | Lid-close disconnects = closed conversations in v0.1. v0.2 hardens this. |
| Cross-tailnet pairing (PAKE codes) | v1. |
| Multi-agent / group channels | v2. (But envelope schema MUST include `from_agent`/`to_agent` from v0.1 — see §4.) |
| Conversation transcript export to `briefs/` | v1. |
| Persistent durable storage | v0.1 keeps conversation state in-memory. Daemon restart = lost state. v0.2 may add SQLite. |
| Mobile clients / QR codes | v2. |

### Deferred safety, kept as code TODOs

These are real concerns from the cept audit, but not v0.1-blocking. Mark each with a `# TODO(v0.2-safety):` comment in code:

- LLM token budget tracking
- Rate limit on `say_to_peer`
- Token rotation command
- `interrupted` conversation state + reconnect resume
- `ack.reason` richer enum

---

## 3. Resolved-during-build-plan decisions

### 3.1 Multi-agent future-proofing — DECIDE NOW (resolves SPEC §13 Q7)

**Decision:** envelopes carry optional `from_agent` and `to_agent` string fields from v0.1. In v0.1, both default to `"default"` if omitted; only one agent runs per daemon. v0.1 daemons MUST set them. v0.1 daemons MUST NOT reject envelopes that omit them (treat as `"default"`).

**Why:** the cost is two ignored fields in v0.1. The benefit is that v2 multi-agent group channels don't require a breaking schema change. Wire-format stability is cheap to design in upfront and expensive to fix later.

**Concrete envelope shape (v0.1 — final):**

```json
{
  "type": "say",
  "msg_id": "<uuid-v4>",
  "from": "mac-a.tailnet.ts.net",
  "to": "mac-b.tailnet.ts.net",
  "from_agent": "default",
  "to_agent": "default",
  "ts": "2026-05-01T14:23:01.234Z",
  "conv_id": "c-001",
  "content": "<English text>"
}
```

### 3.2 Token budget default validation — DEFERRED with stated default

**Decision:** v0.1 ships without LLM token budget enforcement. v0.2 ships with a default of 200k input + 200k output per `conv_id`, configurable.

**Why:** any default I pick is a guess until we measure. Better to ship without it, measure costs in the v0.1 soak, then set a defensible default in v0.2.

### 3.3 Reconnect resume — DEFERRED, keep simple

**Decision:** v0.1 closes all `OPEN` conversations on disconnect. No replay, no resume. Agents are notified `peer disconnected` and must start a new `conv_id` to continue.

**Why:** resume requires per-conversation seq numbers, replay buffers, and idempotent envelope handling. All real, all complex, all postponable. v0.2 adds it after we know whether real users hate the disconnect-loses-context behavior.

---

## 4. File-by-file dep graph

The order below is the dependency-correct build order. Each node depends only on what's above it.

```
                    ┌─────────────────────────┐
                    │  pyproject.toml          │
                    │  (deps: claude-agent-sdk,│
                    │   websockets, click)     │
                    └────────────┬────────────┘
                                 │
                ┌────────────────┴───────────────┐
                ▼                                ▼
     ┌──────────────────┐              ┌──────────────────┐
     │  config.py       │              │  keychain.py     │
     │  (paths, defaults│              │  (security CLI  │
     │   config TOML)   │              │   wrapper)       │
     └──────────┬───────┘              └────────┬─────────┘
                │                                │
                └────────────────┬──────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  identity.py             │
                    │  (keypair, fingerprint,  │
                    │   self-advertisement)    │
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  discovery.py            │
                    │  (tailscale status, probe│
                    │   known port for /identity)│
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  pairing.py              │
                    │  (POST /pair, accept     │
                    │   prompt, token write)   │
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  protocol.py             │
                    │  (envelope schemas,      │
                    │   serde, conv state mach.)│
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  transport.py            │
                    │  (WS server + client,    │
                    │   bearer auth, ping/pong)│
                    └────────────┬─────────────┘
                                 ▼
            ┌────────────────────┴───────────────────┐
            ▼                                         ▼
  ┌──────────────────┐                    ┌──────────────────┐
  │  tools/          │                    │  daemon.py       │
  │  say_to_peer.py  │ ◄────────────────► │  (orchestrator,  │
  │  end_conv.py     │                    │   conv lifecycle)│
  │  list_convs.py   │                    └────────┬─────────┘
  └──────────────────┘                             ▼
                                          ┌──────────────────┐
                                          │  cli.py          │
                                          │  (init, pair,    │
                                          │   start, log,    │
                                          │   status)        │
                                          └──────────────────┘
```

**Critical observation:** every component above can be unit-tested in isolation against the layer below it. The integration test (real two-Mac conversation) only runs end-to-end after `cli.py` is wired.

---

## 5. Phased build sequence (5 named days)

Each phase has a specific exit criterion. Don't move on until it passes.

### Phase 1 — Foundation (Day 1)

**Build:** `pyproject.toml`, `config.py`, `keychain.py`, `identity.py`.

**Exit criterion:** unit test passes:
- Generate an identity, write keypair fingerprint to Keychain, read it back, fingerprints match.
- Round-trip via `security` CLI verified.
- `config.py` reads `~/.config/mac2mac/config.toml` if present; falls back to defaults; missing file is not an error.

### Phase 2 — Discovery & Pairing (Day 2)

**Build:** `discovery.py`, `pairing.py`. Stand up a stub HTTP server on `tailnet:9442` exposing `GET /mac2mac/identity` and `POST /mac2mac/pair`.

**Exit criterion:**
- On a single Mac, run two daemons on different ports. From one, `discovery.list_peers()` finds the other.
- Pairing handshake completes between the two local daemons. Both Keychains hold the new shared token.
- `mac2mac pair --accept` correctly prompts and writes on the receiver side.

### Phase 3 — Wire Protocol (Day 3)

**Build:** `protocol.py` (envelope schemas, conv state machine, all 6 envelope types, the `OPEN → CLOSING → CLOSED` transitions including the bye-bye invariant).

**Exit criterion:**
- Unit test exercises the state machine with the §11 worked examples (happy path, race close, runaway turn-budget, wrong-tool, implicit silence). All transitions match SPEC §6.
- Round-trip JSON serde for every envelope type.

### Phase 4 — Transport (Day 4)

**Build:** `transport.py` (WS server + client). Wire `protocol.py` envelopes through the WS.

**Exit criterion:**
- Two daemons on the same Mac connect over `ws://localhost:9442/mac2mac/channel` with bearer-token auth.
- Bearer rejection works (`401` on bad token).
- Tailscale-only bind verified (refuses `0.0.0.0`).
- Ping/pong keepalive works; missing pings disconnect.

### Phase 5 — Agent integration (Day 5)

**Build:** `tools/say_to_peer.py`, `tools/end_conversation.py`, `tools/list_conversations.py`. Wire `claude-agent-sdk` agent into `daemon.py` with these tools registered.

**Exit criterion:**
- Local agent receives a message → calls `say_to_peer` → envelope reaches the (other) local daemon → that daemon's agent receives it as a user-turn → agent responds → envelope crosses back → originator's agent gets the reply.
- `end_conversation` triggers structural close on both sides; bye-bye invariant verified (no extra user-turn on the receiving side).

### Phase 6 — CLI & two-Mac integration (Day 6)

**Build:** `cli.py` (`init`, `pair`, `start`, `log`, `status`).

**Exit criterion:** the §1 acceptance test passes on two real Macs in the same tailnet. Conversation runs, hostname is fetched, bye-bye terminates cleanly.

### Phase 7 — Polish (optional, Day 7)

- `mac2mac log <conv_id>` reads daemon log and reconstructs transcript.
- Error messages are debuggable (mentioning `conv_id`, suggesting next step).
- README install instructions verified by following them on a fresh machine.

---

## 6. Test strategy

### Unit tests (per file, fast)

- `keychain.py`: round-trip token write/read.
- `protocol.py`: state machine for each example in SPEC §11.
- `transport.py`: bearer auth pass/fail, ping/pong, bind-address restriction.
- `discovery.py`: parse `tailscale status --json`, probe responses.

### Single-Mac integration tests

- Run two daemons on the same Mac on different ports, force-pair them, exchange envelopes. The full protocol path can be exercised without a second machine.
- This is the workhorse — most bugs land here.

### Two-Mac integration tests

- Run on Daniel's Mac mini + MacBook Pro (or whatever pair is available).
- Manual: Daniel types into Mac A, watches Mac B respond.
- Automated: a shell script spawns `mac2mac start` on each, scripts a known prompt, asserts the reply matches.

### What we explicitly do NOT test in v0.1

- Cross-tailnet (out of scope).
- Sleep/wake survival (deferred to v0.2).
- Multi-conversation parallelism (v0.1 is single conversation at a time).
- Mobile / QR (v2).

---

## 7. Risk register

Risks ranked by impact on the v0.1 ship date. Mitigations are concrete actions.

| Risk | Impact | Mitigation |
|------|--------|-----------|
| `claude-agent-sdk` API for custom tools turns out different from assumed shape | High — could redesign Phase 5 | Read SDK docs IN Phase 1, before any tools code is written. Build a `hello world` tool first. Cept consultation flagged this as a fact-to-verify. |
| `tailscale ip -4` returns inconsistent address across sleep/wake | Medium — affects bind path | Phase 4 includes a `wake-test`: lid-close one Mac, wait 60s, lid-open, verify bind address still resolves. Document any quirks. |
| Bearer token via `security` CLI is too slow on the hot path | Low — Keychain is fast for our access pattern | Cache token in process memory after first read. Re-read only on connect. Cept flagged this as a fact-to-verify. |
| WS frame size limits hurt long English messages | Low — modern WS libraries default to 16MB+ | Set explicit max-frame to 1MB; longer messages get `error: payload_too_large`. Document limit. |
| Agent SDK has hidden loop-prevention that conflicts with our turn budget | Low — would just make our budget redundant | Test in Phase 5: induce a 100-turn loop, observe whether SDK or our daemon stops it first. |

---

## 8. Stop conditions

Stop and re-plan if any of these are true at any phase boundary:

- Phase 5 reveals the SDK doesn't expose user-turn injection cleanly — would force a different agent integration shape.
- Two-Mac integration test (Phase 6) fails repeatedly with timing issues that aren't reproducible single-Mac — suggests a design flaw, not a bug.
- The bye-bye invariant turns out to be implementable only with awkward ordering guarantees — worth a re-spec.

In all cases, write down what was learned, update SPEC + AUTONOMY, then resume.

---

## 9. Definition of "done" for v0.1

Ship checklist:

- [ ] §1 acceptance test passes on two real Macs.
- [ ] All Phase exit criteria met.
- [ ] All TODOs marked `v0.2-safety` (not v0.1 blockers) but no TODO marked `v0.1` is open.
- [ ] README install instructions followed successfully on a fresh Mac.
- [ ] Daemon log readable; `mac2mac log <conv_id>` reconstructs the §1 acceptance test transcript.
- [ ] No raw `anthropic` SDK imports anywhere (`grep -r "import anthropic" src/` returns nothing).
- [ ] No listener bound to `0.0.0.0` (`grep -r "0.0.0.0" src/` returns nothing or only in comments).
- [ ] One commit per phase, each green-tested before moving on.

After v0.1 ships:
- 24h soak with daemons running, idle conversations and occasional pings, on both Macs. Document any sleep/wake bugs (these become the v0.2 backlog).
