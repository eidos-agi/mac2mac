# mac2mac — Autonomy Decisions (v0)

Settled design picks for the v0 build. Lighthouse reads this on every tick. Drift from these without explicit re-decision is failure.

---

## ⚑ PHASE: IMPLEMENTATION

**Spec is FROZEN at commit `38b3dee` (2026-05-01).**

The design phase is complete. Lighthouse iterations from this point forward MUST either:

1. **Produce a code commit** that advances `docs/BUILD-PLAN.md` Phase 1–6 toward the §1 acceptance test (Daniel asks Mac A's agent to ask Mac B for its hostname; bye-bye terminates cleanly), OR
2. **No-op and report** — write nothing, end the iteration, explicitly state that the next unit of progress is implementation work that requires a focused human-driven session.

**Forbidden in this phase (without explicit human re-decision):**
- New SPEC.md sections.
- New worked examples.
- Additional threat-model adversaries.
- TROUBLESHOOTING.md, config-schema reference, or other anticipatory operational docs for code that does not yet exist.
- Resolving "open questions" by writing more spec — open questions are now resolved by writing CODE that forces the answer.

**Why this gate exists:** in iterations 1–3, the loop produced 3 design documents totaling ~1,200 lines and zero lines of code. The agent itself diagnosed the plateau in iteration 3 ("diminishing returns from here on more spec") and immediately proposed three more spec-adjacent docs. That is the spec-hypertrophy failure mode. The gate breaks the cycle by making "more docs" structurally illegal in this phase. To resume docs work, the human must explicitly flip the phase back.

**To exit IMPLEMENTATION phase back to DESIGN:** the human must edit this file to remove this gate. No agent or cron may flip the phase autonomously.

**Lighthouse tick contract under this gate:**
- If the iteration produced a code commit on a Phase 1–6 file: `signal: continue`.
- If the iteration produced a docs change anyway: `drift_category: spec-hypertrophy, signal: pivot`.
- If the iteration no-op'd: `signal: stop` (loop should exit; manual re-engagement required).

---

## What it is

A **persistent agent-to-agent channel** between two Macs. Each Mac runs a `claude-agent-sdk` daemon. The daemons connect over a secure channel and **speak English to each other** — no RPC schema, no command syntax. The wire payload is plain text. From each agent's POV, the other Mac just looks like an unusually interesting human user.

The human on either side talks to their local agent in any normal way (terminal, slack, etc.). The local agent decides when it's worth saying something across the wire — by calling a `say_to_peer` tool. Output of `say_to_peer` becomes a user-turn on the other Mac's agent. Repeat.

## Not what it is

- Not a CLI for one-shot remote command execution.
- Not a controller/worker dispatcher.
- Not RPC with typed payloads.
- Not a streaming-output relay.

## v0 Scope (settled)

| Decision | Pick | Why |
|----------|------|-----|
| Topology | Peer-to-peer, bidirectional | The agents are peers. Either can initiate. No central gateway in v0. |
| Wire payload | Plain English text in JSON envelope `{from, ts, content}` | The agents interpret. No schema is the schema. |
| Send trigger | `say_to_peer(message)` tool, not output broadcast | Agent retains the right to think privately. Internal monologue does not leak. |
| Conversation termination | Implicit silence (no tool call) pauses; `end_conversation(reason)` tool closes; daemon enforces FIVE safety nets: turn budget + LLM token budget + rate limit + idle timeout + agent response timeout | Without termination, two agents recurse forever. Five mechanisms compose to bound count, cost, frequency, and stalls. See SPEC.md §6.2. |
| Token rotation | Per-peer rotation via `mac2mac rotate-token <peer>`; manual default; emergency rotation via unpair/repair | Bearer-token-compromise = full-channel-compromise (per threat model §8.4). Rotation is the compensating control. |
| Threat model documented | Adversary table in SPEC §8.4 covers off-tailnet, same-tailnet-no-token, stolen-token, compromised-local-agent, curious-peer, network-observer, Tailscale-provider | Load-bearing assumption: per-peer bearer token stays secret for peer lifetime. v1 may add per-session ephemeral keys. |
| Transport | Tailscale (WireGuard mesh) + WebSocket | Tailscale gives device identity. WS gives bidirectional streaming. |
| Auth | Bearer token, derived during pairing, stored in macOS Keychain | Defense in depth on top of Tailscale's device auth. |
| Discovery | Probe known port on each tailnet peer (`tailscale status --json` → connect-and-handshake) | Zero codes for two-of-your-own-Macs. List-and-confirm pairing UX. |
| Pairing UX (v0) | Tailscale discovery + click-to-confirm on both sides | No codes typed. Handshake happens over the already-authenticated tailnet path. |
| Pairing UX (v1, deferred) | 6-digit short-lived code (PAKE) for cross-tailnet pairing | Add when Daniel pairs with Vybhav across tailnets, or with throwaway Macs. |
| QR codes | Out of scope until there's a phone in the loop | Two laptops side-by-side don't benefit. |
| SDK language | Python (`claude-agent-sdk`) | Matches Eidos stack (eidos-mail, bot-farm, slack-eidos). |
| LLM cost model | Subscription only — `claude-agent-sdk`, never raw `anthropic` SDK | Per global CLAUDE.md hard constraint. |
| Receiver tool scope | Honors the **receiver's** `.claude/settings.json` permissions, period | Sender does NOT override. Each Mac decides what's allowed on itself. |
| Worker daemon | `launchd` LaunchAgent, auto-restart on crash, reconnect on sleep | Survives reboots and lid-close. |
| Logging | Structured JSON to `~/Library/Logs/mac2mac/` on each Mac | Debuggable from either side. |

## Non-goals for v0

- Multi-tenant / multi-user.
- Public internet exposure (Tailscale only; daemon refuses 0.0.0.0).
- Cross-tailnet pairing.
- Web UI / TUI / mobile.
- Always-on gateway / message queue (defer until a worker Mac proves to sleep too much for P2P).
- More than 2 peers per channel (defer; binary is the simplest case).

## Guardrails (do not violate)

1. **No raw `anthropic` SDK imports** — `claude-agent-sdk` only.
2. **No bypass of receiver's `.claude/settings.json`** — the worker honors its own permissions.
3. **No token in code or env files in repo** — Keychain only, accessed via macOS `security` CLI.
4. **No public-internet listener** — bind to Tailscale interface only, refuse `0.0.0.0`.
5. **No output broadcast** — only `say_to_peer` tool calls cross the wire. Local-agent thinking stays local.
6. **No structured RPC payload** — content field is plain English. If you find yourself reaching for a JSON schema for the *content*, the design has drifted.

## Success metric

- v0.1: After running `mac2mac init` on Mac A, `mac2mac pair` on Mac B confirms the discovered peer, and after `mac2mac start` on both, the two agents can hold a 3-turn conversation in English. Tailscale-only listener verified. Token enforced.
- v0.2: 24h soak — daemons stay up, reconnect after lid-close on either side.

## Re-decision triggers

Update this file (and bump v) if any of these fire:
- Need to pair across non-tailnet Macs (forces v1 PAKE pairing code).
- More than 2 peers on a channel (forces routing).
- Worker Mac proves unreliable on sleep (forces gateway).
- Output broadcast becomes desirable (forces re-think of the say_to_peer abstraction).
- Receiver permissions prove insufficient for sandboxing (forces sender-side allowlist).
