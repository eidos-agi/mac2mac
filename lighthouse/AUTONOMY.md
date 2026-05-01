# mac2mac — Autonomy Decisions (v0)

Settled design picks for the v0 build. Lighthouse reads this on every tick. Drift from these without explicit re-decision is failure.

## Goal
A CLI that lets one Mac dispatch a task to another Mac via Claude Agent SDK and stream the result back.

```
mac2mac --target=worker "build the project and report any test failures"
```

## v0 Scope (settled)

| Decision | Pick | Why |
|----------|------|-----|
| Direction | One-way: controller → worker | Bidirectional is symmetry without a real use case yet. Add later if reverse-initiation matters. |
| Transport | Tailscale (WireGuard mesh) + WebSocket | Tailscale gives device identity for free; WS gives bidirectional streaming. |
| Auth | Bearer token over WS, on top of Tailscale | Tailscale authenticates the *device*, token authenticates the *request*. If a tailnet device is compromised, the worker still rejects without the token. Defense in depth. |
| Token storage | macOS Keychain (`security` CLI) | Don't write tokens to disk in plaintext. |
| Receiver tool scope | Full tool use, scoped by **receiver's** `.claude/settings.json` permissions | Sender does NOT override receiver permissions. The worker Mac decides what's allowed on its own machine. |
| SDK language | Python (`claude-agent-sdk`) | Matches Eidos stack (eidos-mail, bot-farm, slack-eidos). |
| LLM cost model | Subscription only (`claude-agent-sdk`, never raw `anthropic` SDK) | Per global CLAUDE.md hard constraint. |
| UX | CLI: `mac2mac --target=NAME "prompt"` | TUI is premature. Programmatic API falls out for free. |
| Worker daemon | `launchd` LaunchAgent, auto-restart on crash | Survives reboots. Reconnects after sleep. |
| Logging | stdout → file in `~/Library/Logs/mac2mac/`, structured JSON | Debuggable from either side. |

## Non-goals for v0

- Multi-tenant / multi-user — single user, two Macs.
- Public internet exposure — Tailscale only.
- Automatic tool approval for destructive operations — receiver permissions handle this.
- Bidirectional initiation — see Direction above.
- Web UI / TUI / mobile.

## Guardrails (do not violate)

1. **No raw `anthropic` SDK imports** — `claude-agent-sdk` only.
2. **No bypass of receiver's `.claude/settings.json`** — the worker honors its own permissions, period.
3. **No token in code or env files in repo** — keychain only.
4. **No public-internet listener** — bind to Tailscale interface only, refuse 0.0.0.0.
5. **Streaming only** — never buffer entire responses; pipe SDK events to client as they arrive.

## Success metric

- v0.1: `mac2mac --target=worker "echo hello && pwd"` returns worker's `pwd` output, bearer-token auth enforced, Tailscale-only listener verified.
- v0.2: 24h soak — worker daemon stays up, reconnects after laptop sleep on either side.

## Re-decision triggers

Update this file (and bump v) if any of these fire:
- Need to call across non-tailnet Macs (forces real mTLS or different identity layer).
- Multiple users on one Mac (forces per-user auth).
- Need for receiver-initiated calls (forces bidirectional).
- Receiver permissions prove insufficient for sandboxing (forces sender-side allowlist).
