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

    # Fallback RMS threshold used when calibration cannot run.
    # Lower value catches quieter/softer speech; calibration will
    # override this at runtime based on actual ambient noise.
    DEFAULT_ENERGY_THRESHOLD = 300.0

    def __init__(self):
        self._recognizer = sr.Recognizer()
        self._energy_threshold: float = self.DEFAULT_ENERGY_THRESHOLD
        # Resolve a concrete device index before any recording attempt so we
        # never pass device=-1 (sounddevice's "no default set" sentinel) to
        # sd.rec() or sd.InputStream().
        self._input_device: int | None = self._select_input_device()
        self._calibrate()
        self._init_whisper()

    # ── Device selection ──────────────────────────────────────────────────────

    def _select_input_device(self) -> int | None:
        """
        Return a usable input-device index, or None if one cannot be found.

        Strategy
        ────────
        1. Read sd.default.device[0].  If it is not -1 and actually has input
           channels, use it.
        2. Otherwise scan all devices and return the first one that has at
           least one input channel.
        3. If nothing is found, return None and let sounddevice try its own
           default (recording will fail gracefully if the system truly has no
           microphone).
        """
        # ── Try the OS-reported default input ────────────────────────────────
        try:
            default_idx = sd.default.device[0]  # tuple: (input, output)
            if default_idx != -1:
                info = sd.query_devices(default_idx)
                if info["max_input_channels"] > 0:
                    logger.info(
                        "Input device: '%s' (index %d)", info["name"], default_idx
                    )
                    return int(default_idx)
        except Exception as exc:
            logger.debug("Could not read sd.default.device: %s", exc)

        # ── Scan all devices for the first with input channels ────────────────
        try:
            for idx, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    logger.info(
                        "Input device (fallback scan): '%s' (index %d)",
                        dev["name"], idx,
                    )
                    return idx
        except Exception as exc:
            logger.debug("Device scan failed: %s", exc)

        logger.warning(
            "No input device found.  Microphone features will be unavailable."
        )
        return None

    # ── Calibration ───────────────────────────────────────────────────────────

    def _calibrate(self):
        """
        Record 2 seconds of ambient noise and set the RMS energy threshold to
        4× the ambient level (minimum 300).

        If calibration fails for any reason (no mic, device error, etc.) JARVIS
        continues with DEFAULT_ENERGY_THRESHOLD — it never crashes or loops here.
        """
        if self._input_device is None:
            logger.warning(
                "Skipping calibration — no input device available.  "
                "Using default threshold %.0f.", self.DEFAULT_ENERGY_THRESHOLD
            )
            return

        logger.info("Calibrating microphone (2 s) …")
        try:
            samples = sd.rec(
                int(2 * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=self._input_device,
                blocking=True,
            )
            rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
            self._energy_threshold = max(rms * 4.0, 300.0)
            logger.info(
                "Calibration complete.  RMS energy threshold: %.0f",
                self._energy_threshold,
            )
        except Exception as exc:
            logger.warning(
                "Microphone calibration failed (%s) — "
                "using default threshold %.0f.",
                exc, self.DEFAULT_ENERGY_THRESHOLD,
            )
            # Threshold already set to DEFAULT_ENERGY_THRESHOLD in __init__

    # ── STT initialisation ────────────────────────────────────────────────────

    def _init_whisper(self):
        """
        Set up speech-to-text.

        Default: Google STT — free, instant, no quota.

        Opt-in alternatives (set in .env):
          USE_WHISPER=true        → OpenAI Whisper API (needs OPENAI_API_KEY)
          WHISPER_LOCAL_MODEL=base → local openai-whisper (needs pip install openai-whisper)

        Whisper API is NOT auto-enabled even when OPENAI_API_KEY is present,
        because an exceeded quota causes a slow retry delay on every command.
        """
        # ── Local Whisper (offline, no quota) ────────────────────────────────
        # Enabled when the openai-whisper package is installed AND
        # WHISPER_LOCAL_MODEL is explicitly set in .env.
        if os.getenv("WHISPER_LOCAL_MODEL"):
            try:
                import whisper  # type: ignore
                model_name = os.getenv("WHISPER_LOCAL_MODEL", "base")
                logger.info("Loading local Whisper model '%s' …", model_name)
                self._whisper_local = whisper.load_model(model_name)
                self._whisper_mode = "local"
                logger.info("STT mode: local Whisper (%s)", model_name)
                return
            except ImportError:
                logger.warning(
                    "WHISPER_LOCAL_MODEL set but openai-whisper not installed — "
                    "falling back to Google STT."
                )

        # ── Whisper API (opt-in only) ─────────────────────────────────────────
        if os.getenv("USE_WHISPER", "false").lower() == "true":
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                try:
                    from openai import OpenAI
                    self._whisper_client = OpenAI(api_key=api_key)
                    self._whisper_mode = "api"
                    logger.info("STT mode: OpenAI Whisper API (opt-in)")
                    return
                except ImportError:
                    logger.warning("openai package not found — falling back to Google STT.")
            else:
                logger.warning("USE_WHISPER=true but OPENAI_API_KEY not set — falling back.")

        # ── Google STT (default) ──────────────────────────────────────────────
        self._whisper_mode = "google"
        logger.info("STT mode: Google STT (default)")

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
                device=self._input_device,   # explicit index — never -1
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

    def listen_for_wake_word(
        self, pre_speech_timeout: float = 5.0
    ) -> tuple[bool, str]:
        """
        Record a short burst and check for the wake phrase via Google STT.

        Parameters
        ----------
        pre_speech_timeout : float
            Seconds to wait for speech before giving up.  Pass a shorter value
            (e.g. 1.5) when polling for interrupt during TTS playback so that
            each check cycle doesn't block the calling thread for too long.

        Returns
        -------
        (detected: bool, inline_command: str)
            inline_command — text after the wake phrase in the same utterance,
            e.g. "Hey Jarvis what time is it?" → "what time is it?"
        """
        audio = self._record_with_vad(
            pre_speech_timeout=pre_speech_timeout,
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
        Record a full voice command (up to 35 s) after the wake word fires.
        Returns numpy int16 array or None if nothing was heard.
        """
        logger.info("Listening for command …")
        return self._record_with_vad(
            pre_speech_timeout=7.0,
            max_duration=35.0,    # slightly longer to capture full commands
            silence_duration=2.0, # extra buffer so end-of-sentence isn't clipped
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
