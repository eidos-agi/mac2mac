---
name: mac2mac
description: Peer-to-peer agent-to-agent channel between Macs. CLI for sending English messages between paired Claude Code instances; MCP wrapper available too. Use this CLI directly — costs zero tokens until invoked.
user_invocable: true
---

# mac2mac — agent-to-agent channel

Agent-first CLI generated per the cli-forge contract. The MCP shell
(`mac2mac mcp`) is also available, but the CLI is cheaper and more
composable: you can pipe it, script it, schedule it, wrap it in Slack
bots — none of which the MCP supports.

All commands support `--json` and `--quiet`. `--help` is the authoritative
schema — always prefer it to this file if they disagree.

## Trigger

Use this CLI when you need to:
- Send a message to a peer Mac's Claude Code agent and get a reply.
- Continue an existing conversation (multi-turn).
- Structurally end a conversation (without the peer auto-replying).
- List configured peers / check reachability.

Reach for it before any other path. The MCP server (`mac2mac mcp`) is
useful only when you need the call to appear as a structured tool-call
in your transcript; otherwise the CLI is faster.

## Setup

No environment variables required for v0 (loopback / self only).

When the wire layer ships, peers will be configured per-host in
`~/.config/mac2mac/config.toml`. Tokens live in macOS Keychain. The
CLI reads both transparently.

## Commands

```
mac2mac send MESSAGE [--to PEER] [--conv-id ID] [--json] [--quiet]
mac2mac end CONV_ID [--reason TEXT] [--json] [--quiet]
mac2mac peers [--json] [--quiet]
mac2mac mcp                 # run as MCP server (stdio mode, for Claude Code)
```

Run `mac2mac <command> --help` for the full flag list. That help text is
the schema — this file is only the playbook.

## Canonical Workflows

### Ask the peer something and use the reply

```bash
reply=$(mac2mac send "what's the build status?" --to=self --quiet)
echo "peer said: $reply"
```

### Hold a multi-turn conversation

```bash
out=$(mac2mac send "investigate the flaky test" --to=self --json)
conv_id=$(echo "$out" | jq -r '.conv_id // "c-001"')

mac2mac send "any progress?" --to=self --conv-id="$conv_id" --quiet

mac2mac end "$conv_id" --reason="thx" --quiet
```

### Use as MCP inside Claude Code

```bash
# one-time install
claude mcp add mac2mac /path/to/mac2mac/.venv/bin/python -m mac2mac.mcp_server

# now your local agent has say_to_peer / end_conversation / list_peers tools
```

## Safety

- Peer agents run on the peer's machine with the peer's `.claude/settings.json`
  permissions. Sender does NOT override. If you ask the peer to delete files,
  the peer's permission policy decides whether to allow it.
- `end_conversation` is structural — calling it terminates the conversation
  on both sides. There is no undo.
- v0 only supports `--to=self` (loopback). Real cross-Mac transports (Tailscale,
  Slack) ship in subsequent versions.

## Rules for Agents

- **Always use `--json`** unless piping one value to another command — then `--quiet`.
- **Use `mac2mac end CONV_ID`** when you actually want to end. `mac2mac send "bye"`
  produces another user-turn on the peer; it does NOT end the conversation.
- **`--help` is ground truth.** If this skill shows a flag that `--help` does not,
  the skill is stale — trust `--help`.
- **One command per step.** Do not chain multiple `mac2mac send` calls in one
  shell string; read each JSON reply before deciding the next call.
- **Failures are data.** Exit code 2 = usage / unknown peer. Exit code 1 = transport
  not yet implemented. Read the JSON body for details when present.
