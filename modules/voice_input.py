"""
voice_input.py — Microphone capture, wake-word detection, and STT.

Recording stack (no PyAudio, no compilation required)
──────────────────────────────────────────────────────
• sounddevice  — captures audio from the microphone using pre-built PortAudio wheels
• Energy-based VAD — detects speech start/end without any compiled C extension
• SpeechRecognition.recognize_google() — fast wake-word check (pure Python, no mic class used)
• OpenAI Whisper API (or local whisper) — accurate command transcription

Flow
────
1. _record_with_vad()   — returns numpy int16 array when speech + silence detected
2. listen_for_wake_word() — short recording → Google STT → check for wake phrase
3. listen_for_command()   — longer recording → returns numpy array
4. transcribe()           — numpy array → WAV bytes (soundfile) → Whisper API
"""

import io
import logging
import os
import tempfile
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
import speech_recognition as sr

logger = logging.getLogger("JARVIS.VoiceInput")

# Audio capture settings
SAMPLE_RATE  = 16000   # Hz — Whisper and Google STT both prefer 16 kHz
CHUNK_FRAMES = 1024    # frames per read (~64 ms at 16 kHz)

# Wake phrases (lowercase)
WAKE_PHRASES = [
    "hey jarvis",
    "okay jarvis",
    "ok jarvis",
    "hi jarvis",
    "jarvis",
]


class VoiceInput:
    """Handles all microphone input for JARVIS without PyAudio."""

    def __init__(self):
        self._recognizer = sr.Recognizer()
        # RMS energy threshold — calibrated against ambient noise in __init__
        self._energy_threshold: float = 500.0
        self._calibrate()
        self._init_whisper()

    # ── Calibration ───────────────────────────────────────────────────────────

    def _calibrate(self):
        """
        Record 2 seconds of ambient noise via sounddevice and set the
        energy threshold to 4× the ambient RMS level (minimum 300).
        """
        logger.info("Calibrating microphone (2 s) …")
        try:
            samples = sd.rec(
                int(2 * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocking=True,
            )
            rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
            self._energy_threshold = max(rms * 4.0, 300.0)
            logger.info(
                "Calibration complete.  RMS energy threshold: %.0f",
                self._energy_threshold,
            )
        except Exception as exc:
            logger.warning("Microphone calibration failed: %s — using default threshold.", exc)

    # ── Whisper initialisation ────────────────────────────────────────────────

    def _init_whisper(self):
        """
        Set up Whisper transcription.
        Priority:
          1. OpenAI Whisper API  (OPENAI_API_KEY set)
          2. Local whisper model (pip install openai-whisper)
          3. Google STT fallback (always available, free)
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
                "No Whisper available — using Google STT for all transcription."
            )

    # ── Core recording (sounddevice VAD) ─────────────────────────────────────

    def _record_with_vad(
        self,
        pre_speech_timeout: float = 5.0,
        max_duration: float = 30.0,
        silence_duration: float = 1.3,
    ) -> "np.ndarray | None":
        """
        Open the microphone with sounddevice and record until speech then silence.

        Parameters
        ----------
        pre_speech_timeout : float
            Seconds to wait for speech to start before giving up.
        max_duration : float
            Maximum recording length in seconds.
        silence_duration : float
            Seconds of silence after speech that signals end of utterance.

        Returns
        -------
        numpy int16 array of shape (n_samples,) or None if nothing was heard.
        """
        pre_limit     = int(pre_speech_timeout * SAMPLE_RATE / CHUNK_FRAMES)
        silence_limit = int(silence_duration   * SAMPLE_RATE / CHUNK_FRAMES)
        max_chunks    = int(max_duration       * SAMPLE_RATE / CHUNK_FRAMES)

        recorded: list[np.ndarray] = []
        silent_count   = 0
        speech_started = False
        waiting_count  = 0

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
            ) as stream:
                while True:
                    chunk, _ = stream.read(CHUNK_FRAMES)
                    # chunk shape: (CHUNK_FRAMES, 1) — flatten to 1-D
                    mono  = chunk[:, 0]
                    energy = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))

                    if energy > self._energy_threshold:
                        # Speech detected
                        speech_started = True
                        silent_count   = 0
                        recorded.append(mono.copy())

                    elif speech_started:
                        # Accumulate post-speech silence
                        silent_count += 1
                        recorded.append(mono.copy())
                        if silent_count >= silence_limit:
                            break  # end of utterance

                    else:
                        # Still waiting for speech to start
                        waiting_count += 1
                        if waiting_count >= pre_limit:
                            return None  # timeout

                    if len(recorded) >= max_chunks:
                        break

        except Exception as exc:
            logger.error("sounddevice recording error: %s", exc)
            return None

        if not recorded:
            return None

        return np.concatenate(recorded)

    # ── Wake-word detection ───────────────────────────────────────────────────

    def listen_for_wake_word(self) -> tuple[bool, str]:
        """
        Record a short burst and check for the wake phrase via Google STT.

        Returns
        -------
        (detected: bool, inline_command: str)
            inline_command — text after the wake phrase in the same utterance,
            e.g. "Hey Jarvis what time is it?" → "what time is it?"
        """
        audio = self._record_with_vad(
            pre_speech_timeout=5.0,
            max_duration=5.0,
            silence_duration=0.8,
        )
        if audio is None:
            return False, ""

        # Wrap in sr.AudioData so we can use recognize_google without PyAudio
        sr_audio = self._numpy_to_sr_audio(audio)

        try:
            text = self._recognizer.recognize_google(sr_audio).lower().strip()
            logger.debug("Wake-word check heard: '%s'", text)
        except sr.UnknownValueError:
            return False, ""
        except sr.RequestError as exc:
            logger.debug("Google STT wake-word error: %s", exc)
            return False, ""

        for phrase in WAKE_PHRASES:
            if phrase in text:
                remaining = text.replace(phrase, "").strip(" ,.")
                return True, remaining

        return False, ""

    # ── Command capture ───────────────────────────────────────────────────────

    def listen_for_command(self) -> "np.ndarray | None":
        """
        Record a full voice command (up to 30 s) after the wake word fires.
        Returns numpy int16 array or None if nothing was heard.
        """
        logger.info("Listening for command …")
        return self._record_with_vad(
            pre_speech_timeout=7.0,
            max_duration=30.0,
            silence_duration=1.5,
        )

    # ── Transcription ─────────────────────────────────────────────────────────

    def transcribe(self, audio: "np.ndarray | None") -> str:
        """Convert recorded audio to text. Never raises — returns '' on failure."""
        if audio is None or len(audio) == 0:
            return ""

        if self._whisper_mode == "api":
            return self._transcribe_whisper_api(audio)
        elif self._whisper_mode == "local":
            return self._transcribe_whisper_local(audio)
        else:
            return self._transcribe_google(audio)

    def _transcribe_whisper_api(self, audio: np.ndarray) -> str:
        """Use the OpenAI Whisper cloud API."""
        try:
            wav_bytes = self._numpy_to_wav_bytes(audio)
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

    def _transcribe_whisper_local(self, audio: np.ndarray) -> str:
        """Use the locally-installed openai-whisper model."""
        tmp_path = None
        try:
            wav_bytes = self._numpy_to_wav_bytes(audio)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav_bytes)
                tmp_path = tmp.name

            result = self._whisper_local.transcribe(tmp_path, language="en")
            text    = result["text"].strip()
            logger.info("Local Whisper: '%s'", text)
            return text
        except Exception as exc:
            logger.warning("Local Whisper failed (%s) — falling back to Google STT.", exc)
            return self._transcribe_google(audio)
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    def _transcribe_google(self, audio: np.ndarray) -> str:
        """Google STT via SpeechRecognition (no PyAudio required)."""
        try:
            sr_audio = self._numpy_to_sr_audio(audio)
            text = self._recognizer.recognize_google(sr_audio)
            logger.info("Google STT: '%s'", text)
            return text
        except sr.UnknownValueError:
            logger.info("Google STT: audio not understood.")
            return ""
        except sr.RequestError as exc:
            logger.error("Google STT request error: %s", exc)
            return ""

    # ── Audio conversion helpers ──────────────────────────────────────────────

    @staticmethod
    def _numpy_to_wav_bytes(audio: np.ndarray) -> bytes:
        """
        Convert a 1-D int16 numpy array to in-memory WAV bytes using soundfile.
        soundfile has a pre-built wheel (no compilation needed).
        """
        buf = io.BytesIO()
        sf.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    @staticmethod
    def _numpy_to_sr_audio(audio: np.ndarray) -> sr.AudioData:
        """
        Wrap a 1-D int16 numpy array in an sr.AudioData object so that
        SpeechRecognition's recognize_*() methods can process it —
        without ever touching sr.Microphone or PyAudio.
        """
        return sr.AudioData(audio.tobytes(), SAMPLE_RATE, 2)  # 2 bytes = int16
