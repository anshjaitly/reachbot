"""
ReachBot — Text-to-Speech Feedback

Gives the robot a voice so users know what it's doing.
Especially important for seniors who can't watch a screen.

Priority order:
  1. pyttsx3 (offline, fast, works on Pi with no internet)
  2. Stub (prints to console — always works)

Phrases follow a consistent pattern:
  - Confirmation:  "Got it, looking for the remote."
  - Status:        "Found it. Moving now."
  - Error:         "Sorry, I couldn't find the remote."
  - Done:          "Here you go."

Usage:
    from tts import Speaker
    speaker = Speaker()
    speaker.say("Got it, looking for the phone.")
    speaker.confirm("remote")        # "Got it, looking for the remote."
    speaker.found("remote")          # "Found it. Moving now."
    speaker.not_found("remote")      # "Sorry, I couldn't see the remote."
    speaker.out_of_reach()           # "That's too far for me to reach."
    speaker.done()                   # "Here you go."
    speaker.estop()                  # "Emergency stop. Returning home."
"""

import logging
import threading
from typing import Optional

log = logging.getLogger(__name__)

# Try pyttsx3 first — offline TTS, works on Raspberry Pi
try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False
    log.info("pyttsx3 not installed — TTS in stub (print) mode. "
             "Install with: pip install pyttsx3")


# ---------------------------------------------------------------------------
# Canned phrases — tweak wording here to adjust how ReachBot sounds
# ---------------------------------------------------------------------------

PHRASES = {
    "confirm":       "Got it, looking for the {object}.",
    "found":         "Found it. Moving now.",
    "not_found":     "Sorry, I couldn't see the {object}. Try moving it into view.",
    "out_of_reach":  "That's a bit too far. Can you bring it a little closer?",
    "grabbing":      "Almost there.",
    "done":          "Here you go.",
    "home":          "Returning home.",
    "estop":         "Emergency stop. Returning to home position.",
    "ready":         "ReachBot ready. Say ReachBot to wake me up.",
    "listening":     "I'm listening.",
    "no_command":    "I didn't catch that. Try saying: pick up my remote.",
    "error":         "Something went wrong. Please try again.",
    "wake":          "Yes?",
}


class Speaker:
    """Thread-safe TTS speaker with graceful hardware fallback.

    Every speak() call runs in a background thread so it never blocks
    the main control loop.
    """

    def __init__(self, rate: int = 155, volume: float = 0.9,
                 voice_gender: str = "female"):
        self._rate = rate
        self._volume = volume
        self._engine: Optional[object] = None
        self._lock = threading.Lock()
        self._stub = not PYTTSX3_AVAILABLE

        if PYTTSX3_AVAILABLE:
            self._init_engine(voice_gender)
        else:
            log.warning("TTS stub mode — spoken lines printed to console.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def say(self, text: str, blocking: bool = False) -> None:
        """Speak arbitrary text. Non-blocking by default."""
        if blocking:
            self._speak(text)
        else:
            t = threading.Thread(target=self._speak, args=(text,), daemon=True)
            t.start()

    # Convenience methods — use these in main.py instead of raw strings

    def confirm(self, object_name: str) -> None:
        self.say(PHRASES["confirm"].format(object=object_name))

    def found(self, object_name: str = "") -> None:
        self.say(PHRASES["found"])

    def not_found(self, object_name: str) -> None:
        self.say(PHRASES["not_found"].format(object=object_name))

    def out_of_reach(self) -> None:
        self.say(PHRASES["out_of_reach"])

    def grabbing(self) -> None:
        self.say(PHRASES["grabbing"])

    def done(self) -> None:
        self.say(PHRASES["done"])

    def home(self) -> None:
        self.say(PHRASES["home"])

    def estop(self) -> None:
        # E-stop is blocking — user must hear this immediately
        self.say(PHRASES["estop"], blocking=True)

    def ready(self) -> None:
        self.say(PHRASES["ready"])

    def listening(self) -> None:
        self.say(PHRASES["listening"])

    def no_command(self) -> None:
        self.say(PHRASES["no_command"])

    def wake(self) -> None:
        self.say(PHRASES["wake"])

    def error(self) -> None:
        self.say(PHRASES["error"])

    @property
    def is_stub(self) -> bool:
        return self._stub

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _init_engine(self, voice_gender: str) -> None:
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self._rate)
            engine.setProperty("volume", self._volume)

            # Try to find a matching voice
            voices = engine.getProperty("voices")
            target = voice_gender.lower()
            for v in voices:
                if target in v.name.lower() or target in (v.gender or "").lower():
                    engine.setProperty("voice", v.id)
                    break

            self._engine = engine
            log.info("TTS engine ready (pyttsx3, rate=%d)", self._rate)
        except Exception as exc:
            log.warning("pyttsx3 init failed (%s) — falling back to stub", exc)
            self._stub = True
            self._engine = None

    def _speak(self, text: str) -> None:
        log.info("[TTS] %s", text)
        if self._stub or self._engine is None:
            print(f"🔊 {text}")
            return
        with self._lock:
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception as exc:
                log.warning("TTS speak failed: %s — printing instead", exc)
                print(f"🔊 {text}")
