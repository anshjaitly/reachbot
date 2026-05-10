"""
ReachBot — Voice Command Listener

Records audio from the microphone using voice activity detection (VAD):
listens in short chunks, starts recording when speech is detected, stops
when silence returns. Transcribes via OpenAI Whisper API (or a local
Whisper model when no API key is set) and returns the command string.
"""

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

try:
    import numpy as np
    import sounddevice as sd
    import scipy.io.wavfile as wav
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False
    log.warning("sounddevice / scipy not installed — stub mode")

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import whisper as local_whisper
    LOCAL_WHISPER_AVAILABLE = True
except ImportError:
    LOCAL_WHISPER_AVAILABLE = False


class VoiceCommandListener:
    """Listens for voice commands with automatic silence detection.

    Flow:
      1. Calibrate noise floor for 0.5s at startup.
      2. Poll audio in CHUNK_S chunks.
      3. When a chunk's RMS exceeds the noise floor × SPEECH_THRESHOLD,
         start buffering audio.
      4. After SILENCE_CHUNKS consecutive quiet chunks, stop and transcribe.
      5. Return the command text if the wake word is present, else None.
    """

    SAMPLE_RATE = 16000
    CHUNK_S = 0.3           # Length of each audio poll chunk (seconds)
    MAX_RECORD_S = 8.0      # Hard cap — stop recording after this long
    SILENCE_CHUNKS = 5      # Quiet chunks in a row → end of utterance
    SPEECH_THRESHOLD = 2.5  # RMS must be this × noise floor to count as speech
    MIN_SPEECH_CHUNKS = 2   # Ignore blips shorter than this

    def __init__(self, wake_word: str = "reachbot"):
        self.wake_word = wake_word.lower()
        self._noise_rms = 300.0   # Default; overwritten by calibrate()
        self._openai_client = None
        self._local_model = None
        self._chunk_samples = int(self.CHUNK_S * self.SAMPLE_RATE)

        if not AUDIO_AVAILABLE:
            log.warning("Audio libraries missing — stub mode active")
            return

        # Prefer OpenAI Whisper API; fall back to local model; fall back to stub
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key and OPENAI_AVAILABLE:
            self._openai_client = OpenAI(api_key=api_key)
            log.info("Voice: using OpenAI Whisper API")
        elif LOCAL_WHISPER_AVAILABLE:
            log.info("Voice: loading local Whisper model (base.en)…")
            self._local_model = local_whisper.load_model("base.en")
            log.info("Voice: local Whisper ready")
        else:
            log.warning(
                "No Whisper backend available. "
                "Set OPENAI_API_KEY or install openai-whisper."
            )

        self.calibrate()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def calibrate(self, duration_s: float = 0.5) -> None:
        """Measure ambient noise level so VAD threshold adapts to the room."""
        if not AUDIO_AVAILABLE:
            return
        log.debug("Calibrating noise floor…")
        samples = sd.rec(
            int(duration_s * self.SAMPLE_RATE),
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="int16",
        )
        sd.wait()
        self._noise_rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
        # Guard against a completely silent room (e.g. simulation env)
        self._noise_rms = max(self._noise_rms, 50.0)
        log.info("Noise floor RMS: %.1f", self._noise_rms)

    def listen(self) -> Optional[str]:
        """Block until an utterance is captured, then return the command.

        Returns the command text (wake word stripped) if the wake word was
        spoken, otherwise None.
        """
        if not AUDIO_AVAILABLE or (
            self._openai_client is None and self._local_model is None
        ):
            return self._stub_listen()

        log.debug("Listening…")
        threshold = self._noise_rms * self.SPEECH_THRESHOLD
        max_chunks = int(self.MAX_RECORD_S / self.CHUNK_S)

        buffer: list = []
        speech_chunks = 0
        silence_run = 0
        recording = False

        for _ in range(max_chunks):
            chunk = sd.rec(
                self._chunk_samples,
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="int16",
            )
            sd.wait()
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

            if rms >= threshold:
                if not recording:
                    log.debug("Speech detected (RMS %.0f > %.0f)", rms, threshold)
                    recording = True
                speech_chunks += 1
                silence_run = 0
                buffer.append(chunk)
            elif recording:
                silence_run += 1
                buffer.append(chunk)  # Keep trailing silence for natural endings
                if silence_run >= self.SILENCE_CHUNKS:
                    log.debug("Silence detected — end of utterance")
                    break
            # Quiet before speech starts → keep waiting, don't buffer

        if speech_chunks < self.MIN_SPEECH_CHUNKS:
            log.debug("Too short to be speech (%d chunks)", speech_chunks)
            return None

        audio = np.concatenate(buffer, axis=0)
        return self._transcribe(audio)

    # ------------------------------------------------------------------
    # Transcription backends
    # ------------------------------------------------------------------

    def _transcribe(self, audio: "np.ndarray") -> Optional[str]:
        """Send audio to Whisper (API or local) and extract the command."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav.write(tmp.name, self.SAMPLE_RATE, audio)
            tmp_path = Path(tmp.name)

        try:
            text = self._run_whisper(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        if text is None:
            return None

        text = text.lower().strip()
        log.info("Transcription: %r", text)

        if self.wake_word not in text:
            log.debug("Wake word %r not in transcription", self.wake_word)
            return None

        command = text.split(self.wake_word, 1)[1]
        command = command.lstrip(",. ").strip()
        return command if command else None

    def _run_whisper(self, wav_path: Path) -> Optional[str]:
        """Call whichever Whisper backend is available."""
        if self._openai_client is not None:
            try:
                with open(wav_path, "rb") as f:
                    response = self._openai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=f,
                        language="en",
                    )
                return response.text
            except Exception as exc:
                log.error("Whisper API error: %s", exc)
                return None

        if self._local_model is not None:
            try:
                result = self._local_model.transcribe(
                    str(wav_path), language="en", fp16=False
                )
                return result.get("text", "")
            except Exception as exc:
                log.error("Local Whisper error: %s", exc)
                return None

        return None

    # ------------------------------------------------------------------
    # Stub (no hardware / no API key)
    # ------------------------------------------------------------------

    def _stub_listen(self) -> Optional[str]:
        """Development stub: read typed commands from stdin."""
        try:
            text = input("[stub voice] Type command (or Enter to skip): ")
        except EOFError:
            return None
        text = text.lower().strip()
        if not text:
            return None
        if self.wake_word in text:
            return text.split(self.wake_word, 1)[1].lstrip(",. ").strip()
        return text  # Allow commands without wake word in stub mode
