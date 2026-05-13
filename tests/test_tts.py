"""
Tests for Speaker TTS module — stub mode, phrase formatting, thread safety.
Run with: python -m pytest tests/ -v
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from tts import Speaker, PHRASES


@pytest.fixture
def speaker():
    """Speaker always in stub mode for tests."""
    with patch("tts.PYTTSX3_AVAILABLE", False):
        s = Speaker()
    return s


class TestSpeakerStubMode:
    def test_is_stub_when_no_pyttsx3(self, speaker):
        assert speaker.is_stub is True

    def test_say_prints_to_stdout(self, speaker, capsys):
        speaker.say("hello world", blocking=True)
        out = capsys.readouterr().out
        assert "hello world" in out

    def test_confirm_includes_object_name(self, speaker, capsys):
        speaker.confirm("remote")
        import time; time.sleep(0.05)  # let thread finish
        out = capsys.readouterr().out
        assert "remote" in out

    def test_not_found_includes_object_name(self, speaker, capsys):
        speaker.not_found("glasses")
        import time; time.sleep(0.05)
        out = capsys.readouterr().out
        assert "glasses" in out

    def test_done_speaks(self, speaker, capsys):
        speaker.done()
        import time; time.sleep(0.05)
        out = capsys.readouterr().out
        assert len(out.strip()) > 0

    def test_estop_is_blocking(self, speaker, capsys):
        # estop() is blocking=True so output is immediate
        speaker.estop()
        out = capsys.readouterr().out
        assert len(out.strip()) > 0

    def test_all_convenience_methods_dont_crash(self, speaker):
        for method in [
            speaker.found, speaker.out_of_reach, speaker.grabbing,
            speaker.home, speaker.ready, speaker.listening,
            speaker.no_command, speaker.wake, speaker.error,
        ]:
            method()  # Should not raise


class TestPhraseContent:
    def test_confirm_phrase_has_object_placeholder(self):
        assert "{object}" in PHRASES["confirm"]

    def test_not_found_phrase_has_object_placeholder(self):
        assert "{object}" in PHRASES["not_found"]

    def test_all_required_phrases_exist(self):
        required = ["confirm", "found", "not_found", "out_of_reach",
                    "done", "estop", "ready", "listening", "error"]
        for key in required:
            assert key in PHRASES, f"Missing phrase: {key}"

    def test_phrases_are_nonempty_strings(self):
        for key, phrase in PHRASES.items():
            assert isinstance(phrase, str) and len(phrase) > 0, \
                f"Phrase '{key}' is empty"


class TestSpeakerWithPyttsx3:
    def test_falls_back_to_stub_if_init_fails(self):
        mock_pyttsx3 = MagicMock()
        mock_pyttsx3.init.side_effect = RuntimeError("no audio")
        import sys
        with patch("tts.PYTTSX3_AVAILABLE", True), \
             patch.dict(sys.modules, {"pyttsx3": mock_pyttsx3}), \
             patch("tts.pyttsx3", mock_pyttsx3, create=True):
            s = Speaker()
        assert s.is_stub is True

    def test_uses_engine_when_available(self, capsys):
        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = []  # no voices
        mock_pyttsx3 = MagicMock()
        mock_pyttsx3.init.return_value = mock_engine
        import sys
        with patch("tts.PYTTSX3_AVAILABLE", True), \
             patch.dict(sys.modules, {"pyttsx3": mock_pyttsx3}), \
             patch("tts.pyttsx3", mock_pyttsx3, create=True):
            s = Speaker()
            s.say("test phrase", blocking=True)
        mock_engine.say.assert_called_once_with("test phrase")
        mock_engine.runAndWait.assert_called_once()
