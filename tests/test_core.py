"""Unit tests for mac2mac.core — the business logic both surfaces share."""

import pytest

from mac2mac import core


def test_say_to_peer_self_loopback() -> None:
    reply = core.say_to_peer("hello world")
    assert "you said: hello world" in reply


def test_say_to_peer_explicit_self() -> None:
    reply = core.say_to_peer("ping", peer="self")
    assert "you said: ping" in reply


def test_say_to_peer_mac_transport_not_yet_implemented() -> None:
    with pytest.raises(NotImplementedError):
        core.say_to_peer("hi", peer="mac://other.tailnet.ts.net")


def test_say_to_peer_slack_transport_not_yet_implemented() -> None:
    with pytest.raises(NotImplementedError):
        core.say_to_peer("hi", peer="slack://#mac2mac")


def test_say_to_peer_unknown_peer_raises() -> None:
    with pytest.raises(ValueError):
        core.say_to_peer("hi", peer="garbage")


def test_end_conversation_returns_close_message() -> None:
    out = core.end_conversation("c-123", reason="done")
    assert "c-123 closed" in out
    assert "done" in out


def test_list_peers_includes_self() -> None:
    peers = core.list_peers()
    assert any("self" in p for p in peers)
