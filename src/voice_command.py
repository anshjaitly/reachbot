"""
ReachBot — Voice Command Listener

Records audio from the default microphone, transcribes it via the
OpenAI Whisper API, and returns the command string when the user
addresses ReachBot by its wake word.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

try:
    import sounddevice as sd
    import scipy.io.wavfile as wav
    from openai import OpenAI
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False
    log.warning(
        "Audio/OpenAI libraries not available — running in stub mode"
    )


class VoiceCommandListener:
    """Listens for voice commands via the default microphone."""

    SAMPLE_RATE = 16000
    DURATION_S = 5.0  # Max recording length per command

    def __init__(self, wake_word: str = "reachbot"):
        self.wake_word = wake_word.lower()
        self.client = None
        if HARDWARE_AVAILABLE:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                log.warning(
                    "OPENAI_API_KEY not set — Whisper API unavailable"
                )
            else:
                self.client = OpenAI(api_key=api_key)

    def listen(self) -> Optional[str]:
        """Record audio, transcribe, return command if wake word present.

        Returns:
            The command text (with wake word stripped) if detected,
            otherwise None.
        """
        if not HARDWARE_AVAILABLE or self.client is None:
            return self._stub_listen()

        log.debug("Recording %ss of audio...", self.DURATION_S)
        audio = sd.rec(
            int(self.DURATION_S * self.SAMPLE_RATE),
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="int16",
        )
        sd.wait()

        # Save to a temp WAV file for the API
        with tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False
        ) as tmp:
            wav.write(tmp.name, self.SAMPLE_RATE, audio)
            tmp_path = Path(tmp.name)

        try:
            with open(tmp_path, "rb") as f:
                response = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                )
            text = response.text.lower().strip()
            log.debug("Transcription: %r", text)

            # Wake word check
            if self.wake_word in text:
                # Strip wake word and surrounding punctuation
                command = text.split(self.wake_word, 1)[1]
                command = command.lstrip(",. ").strip()
                return command if command else None
            return None
        finally:
            tmp_path.unlink(missing_ok=True)

    def _stub_listen(self) -> Optional[str]:
        """Stub mode: prompt the user via console for a typed command.

        Used during development without microphone or API key.
        """
        try:
            text = input("[stub voice] Type command (or Enter to skip): ")
        except EOFError:
            return None
        text = text.lower().strip()
        if not text:
            return None
        if self.wake_word in text:
            return text.split(self.wake_word, 1)[1].lstrip(",. ").strip()
        # Allow direct commands in stub mode without wake word
        return text
