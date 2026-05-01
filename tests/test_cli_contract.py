"""Verifies mac2mac CLI satisfies the cli-forge Agent-First CLI Contract.

Each rule from cli-forge/templates/skill-template.md gets a test.
"""

import json
import subprocess
import sys


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mac2mac", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def test_help_lists_every_subcommand() -> None:
    result = _run("--help")
    for cmd in ("send", "end", "peers", "mcp"):
        assert cmd in result.stdout, f"`{cmd}` missing from --help output"


def test_send_help_lists_every_flag() -> None:
    result = _run("send", "--help")
    for flag in ("--to", "--conv-id", "--json", "--quiet", "message"):
        assert flag in result.stdout, f"`{flag}` missing from `send --help`"


def test_send_json_output_is_parseable() -> None:
    result = _run("send", "hello", "--to", "self", "--json")
    payload = json.loads(result.stdout)
    assert "reply" in payload
    assert "peer" in payload
    assert payload["peer"] == "self"
    assert "you said: hello" in payload["reply"]


def test_send_quiet_output_is_bare_value() -> None:
    result = _run("send", "ping", "--to", "self", "--quiet")
    assert result.stdout.strip() == "[mac2mac echo via self-loop] you said: ping"


def test_missing_required_arg_exits_2() -> None:
    result = _run("send", check=False)
    assert result.returncode == 2, "missing required arg should exit 2"


def test_unknown_peer_exits_2() -> None:
    result = _run("send", "hello", "--to", "garbage", check=False)
    assert result.returncode == 2
    assert "Error" in result.stderr


def test_unimplemented_transport_exits_1() -> None:
    result = _run("send", "hello", "--to", "mac://other.tailnet.ts.net", check=False)
    assert result.returncode == 1
    assert "Error" in result.stderr


def test_peers_json() -> None:
    result = _run("peers", "--json")
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert any(p.get("id") == "self" for p in payload)


def test_peers_quiet() -> None:
    result = _run("peers", "--quiet")
    assert "self" in result.stdout


def test_end_json() -> None:
    result = _run("end", "c-test", "--reason", "done", "--json")
    payload = json.loads(result.stdout)
    assert payload["closed"] is True
    assert payload["conv_id"] == "c-test"
    assert payload["reason"] == "done"


def test_no_interactive_prompts() -> None:
    """CLI must never block waiting for stdin input."""
    result = subprocess.run(
        [sys.executable, "-m", "mac2mac", "send", "hello", "--to", "self"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0
