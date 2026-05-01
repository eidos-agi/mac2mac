"""End-to-end test: CLI is a thin shell over core. Same input → same output."""

import subprocess
import sys

from mac2mac import core


def _run_cli(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "mac2mac", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_cli_send_matches_core() -> None:
    cli_out = _run_cli("send", "hello from cli")
    core_out = core.say_to_peer("hello from cli")
    assert cli_out == core_out


def test_cli_send_with_to_self() -> None:
    cli_out = _run_cli("send", "ping", "--to", "self")
    assert "you said: ping" in cli_out


def test_cli_end_conversation() -> None:
    cli_out = _run_cli("end", "c-cli-test", "--reason", "automated test")
    assert "c-cli-test closed" in cli_out
    assert "automated test" in cli_out


def test_cli_peers() -> None:
    cli_out = _run_cli("peers")
    assert "self" in cli_out
