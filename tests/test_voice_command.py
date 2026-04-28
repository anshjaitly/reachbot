"""
Tests for voice command parsing and stub listener.
Run with: python -m pytest tests/ -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from main import parse_target_object
from voice_command import VoiceCommandListener


# ---------------------------------------------------------------------------
# parse_target_object
# ---------------------------------------------------------------------------

class TestParseTargetObject:
    @pytest.mark.parametrize("command,expected", [
        ("pick up my glasses",      "glasses"),
        ("grab the remote",         "remote"),
        ("get me the phone",        "phone"),
        ("fetch my keys",           "keys"),
        ("pick up a bottle",        "bottle"),
        ("grab my pill bottle",     "pill"),
        ("get the cup",             "cup"),
        ("pick up glasses please",  "glasses"),
    ])
    def test_known_phrases(self, command, expected):
        assert parse_target_object(command) == expected

    @pytest.mark.parametrize("command", [
        "hello reachbot",
        "how are you",
        "what is the weather",
        "",
        "   ",
    ])
    def test_no_trigger_returns_none(self, command):
        assert parse_target_object(command) is None

    def test_case_insensitive(self):
        assert parse_target_object("PICK UP MY GLASSES") == "glasses"

    def test_extra_whitespace(self):
        result = parse_target_object("  grab   the   remote  ")
        assert result == "remote"


# ---------------------------------------------------------------------------
# VoiceCommandListener — stub mode
# ---------------------------------------------------------------------------

class TestVoiceCommandListenerStub:
    def test_stub_strips_wake_word(self, monkeypatch):
        listener = VoiceCommandListener(wake_word="reachbot")
        monkeypatch.setattr("builtins.input", lambda _: "reachbot pick up my glasses")
        result = listener._stub_listen()
        assert result == "pick up my glasses"

    def test_stub_allows_direct_command_without_wake_word(self, monkeypatch):
        listener = VoiceCommandListener(wake_word="reachbot")
        monkeypatch.setattr("builtins.input", lambda _: "grab the remote")
        result = listener._stub_listen()
        assert result == "grab the remote"

    def test_stub_empty_input_returns_none(self, monkeypatch):
        listener = VoiceCommandListener(wake_word="reachbot")
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = listener._stub_listen()
        assert result is None

    def test_stub_eof_returns_none(self, monkeypatch):
        listener = VoiceCommandListener(wake_word="reachbot")
        def raise_eof(_):
            raise EOFError
        monkeypatch.setattr("builtins.input", raise_eof)
        result = listener._stub_listen()
        assert result is None

    def test_wake_word_custom(self, monkeypatch):
        listener = VoiceCommandListener(wake_word="robot")
        monkeypatch.setattr("builtins.input", lambda _: "robot fetch my keys")
        result = listener._stub_listen()
        assert "keys" in result
