"""
voice_output.py — Text-to-speech and audio playback.

TTS priority
────────────
1. ElevenLabs API  — smooth British male voice (Daniel / configurable)
2. pyttsx3         — Windows SAPI fallback (offline, robotic but always works)

Activation sound
────────────────
Generated once via numpy and cached to sounds/activation.wav.
Sounds like a rising Iron-Man-style electronic chime.
"""

import io
import logging
import os
import tempfile
import wave
from pathlib import Path

import numpy as np
import pygame

logger = logging.getLogger("JARVIS.VoiceOutput")

# ElevenLabs "Daniel" — British male, clear and authoritative.
# Override with ELEVENLABS_VOICE_ID in your .env
DEFAULT_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"
SOUNDS_DIR = Path("sounds")


class VoiceOutput:
    """Manages all audio output for JARVIS."""

    def __init__(self):
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
        self._init_elevenlabs()
        self._init_fallback_tts()
        self._ensure_activation_sound()

    # ── ElevenLabs setup ──────────────────────────────────────────────────────

    def _init_elevenlabs(self):
        api_key  = os.getenv("ELEVENLABS_API_KEY")
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID)

        if not api_key:
            logger.warning("ELEVENLABS_API_KEY not set — using fallback TTS.")
            self._el_client  = None
            self._voice_id   = None
            return

        try:
            from elevenlabs.client import ElevenLabs  # type: ignore
            self._el_client = ElevenLabs(api_key=api_key)
            self._voice_id  = voice_id
            logger.info("ElevenLabs TTS ready (voice: %s).", voice_id)
        except ImportError:
            logger.warning(
                "elevenlabs package not installed — using fallback TTS.  "
                "Run: pip install elevenlabs"
            )
            self._el_client = None

    # ── Fallback TTS (pyttsx3 / Windows SAPI) ────────────────────────────────

    def _init_fallback_tts(self):
        try:
            import pyttsx3  # type: ignore

            engine = pyttsx3.init()
            # Prefer a deeper/male voice if available
            for v in engine.getProperty("voices"):
                name = v.name.lower()
                if "david" in name or "mark" in name or "george" in name:
                    engine.setProperty("voice", v.id)
                    break
            engine.setProperty("rate", 170)
            engine.setProperty("volume", 0.92)
            self._fallback_tts = engine
            logger.info("Fallback TTS (pyttsx3) ready.")
        except Exception as exc:
            logger.warning("pyttsx3 unavailable: %s", exc)
            self._fallback_tts = None

    # ── Activation sound ──────────────────────────────────────────────────────

    def _ensure_activation_sound(self):
        """Generate the activation chime if it doesn't already exist."""
        SOUNDS_DIR.mkdir(exist_ok=True)
        self._activation_path = SOUNDS_DIR / "activation.wav"
        if not self._activation_path.exists():
            self._generate_activation_sound()

    def _generate_activation_sound(self):
        """
        Synthesise a futuristic rising-chime activation sound.
        Three-stage signature:
          1. Rapid frequency sweep  400 → 900 Hz
          2. Short sharp ping       1 400 Hz
          3. Sustained confirmation 1 800 Hz (fades out)
        """
        sr = 22050  # sample rate

        def make_tone(freq_start, freq_end, duration, amplitude, fade="out"):
            n = int(sr * duration)
            t = np.linspace(0, duration, n, endpoint=False)
            freqs = np.linspace(freq_start, freq_end, n)
            wave_data = amplitude * np.sin(2 * np.pi * freqs * t)
            if fade == "out":
                envelope = np.linspace(1.0, 0.0, n) ** 1.5
            elif fade == "in":
                envelope = np.linspace(0.0, 1.0, n) ** 0.5
            else:
                envelope = np.ones(n)
            return wave_data * envelope

        chirp     = make_tone(400,  900,  0.25, 0.55, fade="in")
        silence   = np.zeros(int(sr * 0.06))
        ping      = make_tone(1400, 1400, 0.18, 0.75, fade="out")
        gap       = np.zeros(int(sr * 0.04))
        confirm   = make_tone(1800, 1600, 0.40, 0.60, fade="out")

        sound = np.concatenate([chirp, silence, ping, gap, confirm])

        # Normalise to prevent clipping
        peak = np.max(np.abs(sound))
        if peak > 0:
            sound = sound / peak * 0.88

        pcm = (sound * 32767).astype(np.int16)

        with wave.open(str(self._activation_path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())

        logger.info("Activation sound generated → %s", self._activation_path)

    def play_activation_sound(self):
        """Play the activation chime and block until it finishes."""
        try:
            snd = pygame.mixer.Sound(str(self._activation_path))
            snd.play()
            # Wait for exact duration (ms)
            pygame.time.wait(int(snd.get_length() * 1000) + 50)
        except Exception as exc:
            logger.debug("Activation sound playback error: %s", exc)

    # ── Main speak function ───────────────────────────────────────────────────

    def speak(self, text: str):
        """Convert text to speech and play it.  Never raises."""
        if not text or not text.strip():
            return

        preview = text[:80] + ("…" if len(text) > 80 else "")
        logger.info("Speaking: %s", preview)

        if self._el_client:
            self._speak_elevenlabs(text)
        elif self._fallback_tts:
            self._speak_pyttsx3(text)
        else:
            logger.error("No TTS engine available — cannot speak.")

    # ── ElevenLabs TTS ────────────────────────────────────────────────────────

    def _speak_elevenlabs(self, text: str):
        """Stream from ElevenLabs, save to temp MP3, play with pygame."""
        tmp_path = None
        try:
            from elevenlabs import VoiceSettings  # type: ignore

            audio_stream = self._el_client.text_to_speech.convert(
                voice_id=self._voice_id,
                text=text,
                model_id="eleven_multilingual_v2",
                output_format="mp3_22050_32",
                voice_settings=VoiceSettings(
                    stability=0.50,
                    similarity_boost=0.75,
                    style=0.10,
                    use_speaker_boost=True,
                ),
            )

            # Collect all chunks then write to temp file
            audio_data = b"".join(audio_stream)

            with tempfile.NamedTemporaryFile(
                suffix=".mp3", delete=False, dir=str(SOUNDS_DIR)
            ) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name

            # Play the MP3
            pygame.mixer.music.load(tmp_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(50)
            pygame.mixer.music.unload()

        except Exception as exc:
            logger.error("ElevenLabs TTS error: %s — falling back.", exc)
            if self._fallback_tts:
                self._speak_pyttsx3(text)
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    # ── pyttsx3 fallback ──────────────────────────────────────────────────────

    def _speak_pyttsx3(self, text: str):
        try:
            self._fallback_tts.say(text)
            self._fallback_tts.runAndWait()
        except Exception as exc:
            logger.error("pyttsx3 TTS error: %s", exc)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self):
        """Release pygame mixer resources."""
        try:
            pygame.mixer.quit()
        except Exception:
            pass
