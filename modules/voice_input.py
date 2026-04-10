"""
voice_input.py — Microphone capture, wake-word detection, and STT.

Pipeline
────────
1. Continuous short-burst listening with SpeechRecognition.
2. Google STT for fast, lightweight wake-word matching.
3. OpenAI Whisper API (or local whisper) for accurate command transcription.
4. Falls back to Google STT if Whisper is unavailable.

Wake phrases recognised
────────────────────────
  "hey jarvis", "jarvis", "okay jarvis", "hi jarvis"
"""

import io
import logging
import os
import tempfile
from pathlib import Path

import speech_recognition as sr

logger = logging.getLogger("JARVIS.VoiceInput")

# Phrases that activate JARVIS (lowercase)
WAKE_PHRASES = [
    "hey jarvis",
    "okay jarvis",
    "ok jarvis",
    "hi jarvis",
    "jarvis",
]


class VoiceInput:
    """Handles all microphone input for JARVIS."""

    def __init__(self):
        self.recognizer = sr.Recognizer()

        # Tweak sensitivity — lower = more sensitive, higher = ignores quieter sounds
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.energy_threshold = 300
        self.recognizer.pause_threshold = 0.8  # silence = end of phrase (seconds)
        self.recognizer.phrase_threshold = 0.3

        self.microphone = sr.Microphone()
        self._calibrate()
        self._init_whisper()

    # ── Calibration ───────────────────────────────────────────────────────────

    def _calibrate(self):
        """Sample ambient noise so the recogniser can set an appropriate threshold."""
        logger.info("Calibrating microphone (2 s) …")
        try:
            with self.microphone as src:
                self.recognizer.adjust_for_ambient_noise(src, duration=2)
            logger.info(
                "Calibration complete.  Energy threshold: %.0f",
                self.recognizer.energy_threshold,
            )
        except Exception as exc:
            logger.warning("Microphone calibration failed: %s", exc)

    # ── Whisper initialisation ────────────────────────────────────────────────

    def _init_whisper(self):
        """
        Set up Whisper transcription.
        Priority:
          1. OpenAI Whisper API  (needs OPENAI_API_KEY)
          2. Local whisper model (needs `pip install openai-whisper`)
          3. Google STT fallback (always available)
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            try:
                from openai import OpenAI
                self._whisper_client = OpenAI(api_key=api_key)
                self._whisper_mode = "api"
                logger.info("Whisper mode: OpenAI API")
                return
            except ImportError:
                logger.warning("openai package not found — trying local whisper.")

        # Try local whisper
        try:
            import whisper  # type: ignore
            model_name = os.getenv("WHISPER_LOCAL_MODEL", "base")
            logger.info("Loading local Whisper model '%s' …", model_name)
            self._whisper_local = whisper.load_model(model_name)
            self._whisper_mode = "local"
            logger.info("Whisper mode: local (%s)", model_name)
        except ImportError:
            self._whisper_mode = "google"
            logger.warning(
                "Neither OpenAI API key nor local whisper available. "
                "Falling back to Google STT for all transcription."
            )

    # ── Wake-word detection ───────────────────────────────────────────────────

    def listen_for_wake_word(self) -> tuple[bool, str]:
        """
        Block until audio is detected, then do a quick Google STT check.

        Returns
        -------
        (detected: bool, inline_command: str)
            detected        — True if a wake phrase was found.
            inline_command  — Any text spoken *after* the wake phrase in the
                              same utterance (e.g. "Hey Jarvis, what time is it?").
        """
        with self.microphone as src:
            try:
                # Short burst — just enough to catch the wake word
                audio = self.recognizer.listen(
                    src, timeout=5, phrase_time_limit=5
                )
            except sr.WaitTimeoutError:
                return False, ""
            except Exception as exc:
                logger.debug("Wake-word listen error: %s", exc)
                return False, ""

        try:
            text = self.recognizer.recognize_google(audio).lower().strip()
            logger.debug("Wake-word check heard: '%s'", text)
        except sr.UnknownValueError:
            return False, ""
        except sr.RequestError as exc:
            logger.debug("Google STT wake-word error: %s", exc)
            return False, ""

        for phrase in WAKE_PHRASES:
            if phrase in text:
                # Strip the wake phrase to get the inline command (if any)
                remaining = text.replace(phrase, "").strip(" ,.")
                return True, remaining

        return False, ""

    # ── Command capture ───────────────────────────────────────────────────────

    def listen_for_command(self) -> "sr.AudioData | None":
        """
        Listen for a voice command after the wake word has been detected.
        Returns AudioData or None if nothing was heard within the timeout.
        """
        logger.info("Listening for command …")
        with self.microphone as src:
            try:
                audio = self.recognizer.listen(
                    src, timeout=7, phrase_time_limit=30
                )
                return audio
            except sr.WaitTimeoutError:
                logger.info("No command heard within timeout.")
                return None
            except Exception as exc:
                logger.error("Error capturing command: %s", exc)
                return None

    # ── Transcription ─────────────────────────────────────────────────────────

    def transcribe(self, audio: "sr.AudioData") -> str:
        """
        Convert captured audio to text using the best available STT engine.
        Never raises — returns empty string on total failure.
        """
        if self._whisper_mode == "api":
            result = self._transcribe_whisper_api(audio)
        elif self._whisper_mode == "local":
            result = self._transcribe_whisper_local(audio)
        else:
            result = self._transcribe_google(audio)

        return result.strip()

    def _transcribe_whisper_api(self, audio: "sr.AudioData") -> str:
        """Use the OpenAI Whisper cloud API."""
        try:
            wav_bytes = audio.get_wav_data()
            audio_file = io.BytesIO(wav_bytes)
            audio_file.name = "command.wav"

            response = self._whisper_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="en",
            )
            text = response.text.strip()
            logger.info("Whisper API: '%s'", text)
            return text
        except Exception as exc:
            logger.warning("Whisper API failed (%s) — falling back to Google STT.", exc)
            return self._transcribe_google(audio)

    def _transcribe_whisper_local(self, audio: "sr.AudioData") -> str:
        """Use the locally-installed openai-whisper model."""
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio.get_wav_data())
                tmp_path = tmp.name

            result = self._whisper_local.transcribe(tmp_path, language="en")
            text = result["text"].strip()
            logger.info("Local Whisper: '%s'", text)
            return text
        except Exception as exc:
            logger.warning("Local Whisper failed (%s) — falling back to Google STT.", exc)
            return self._transcribe_google(audio)
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    def _transcribe_google(self, audio: "sr.AudioData") -> str:
        """Google STT — reliable fallback, requires internet."""
        try:
            text = self.recognizer.recognize_google(audio)
            logger.info("Google STT: '%s'", text)
            return text
        except sr.UnknownValueError:
            logger.info("Google STT: audio not understood.")
            return ""
        except sr.RequestError as exc:
            logger.error("Google STT request error: %s", exc)
            return ""
