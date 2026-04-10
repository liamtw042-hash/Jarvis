"""
voice_output.py — Text-to-speech and audio playback.

Playback stack (no pygame, no compilation required)
─────────────────────────────────────────────────────
• sounddevice  — plays numpy float32 arrays directly through the system speaker
• ElevenLabs   — requested as raw PCM (pcm_22050), played in-memory via sounddevice
• pyttsx3      — Windows SAPI5 fallback (pure Python COM, no C extension needed)

Activation sound
────────────────
Generated once as a numpy float32 array; kept in memory and played via sounddevice.
No temp files, no disk I/O, no external libraries beyond sounddevice + numpy.

TTS priority
────────────
1. ElevenLabs API  → PCM stream → sounddevice.play()
2. pyttsx3         → Windows SAPI5 (offline fallback)
"""

import logging
import os

import numpy as np
import sounddevice as sd

logger = logging.getLogger("JARVIS.VoiceOutput")

# ElevenLabs "Daniel" — British male, clear and authoritative.
# Override with ELEVENLABS_VOICE_ID in your .env
DEFAULT_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"

# Sample rate used for the activation chime and ElevenLabs PCM output
PLAYBACK_SR = 22050


class VoiceOutput:
    """Manages all audio output for JARVIS."""

    def __init__(self):
        self._init_elevenlabs()
        self._init_fallback_tts()
        self._generate_activation_sound()

    # ── ElevenLabs setup ──────────────────────────────────────────────────────

    def _init_elevenlabs(self):
        api_key  = os.getenv("ELEVENLABS_API_KEY")
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID)

        if not api_key:
            logger.warning("ELEVENLABS_API_KEY not set — using fallback TTS.")
            self._el_client = None
            self._voice_id  = None
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
            self._voice_id  = None

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
            logger.info("Fallback TTS (pyttsx3 / SAPI5) ready.")
        except Exception as exc:
            logger.warning("pyttsx3 unavailable: %s", exc)
            self._fallback_tts = None

    # ── Activation sound (pure numpy, played via sounddevice) ─────────────────

    def _generate_activation_sound(self):
        """
        Synthesise a futuristic rising-chime activation sound as a float32
        numpy array kept in memory — no disk I/O, no wav file.

        Three-stage signature:
          1. Rapid frequency sweep  400 → 900 Hz  (rising chirp)
          2. Short sharp ping       1 400 Hz
          3. Sustained confirmation 1 800 → 1 600 Hz (fades out)
        """
        sr = PLAYBACK_SR

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
            return (wave_data * envelope).astype(np.float32)

        chirp   = make_tone(400,  900,  0.25, 0.55, fade="in")
        silence = np.zeros(int(sr * 0.06), dtype=np.float32)
        ping    = make_tone(1400, 1400, 0.18, 0.75, fade="out")
        gap     = np.zeros(int(sr * 0.04), dtype=np.float32)
        confirm = make_tone(1800, 1600, 0.40, 0.60, fade="out")

        sound = np.concatenate([chirp, silence, ping, gap, confirm])

        # Normalise to prevent clipping
        peak = np.max(np.abs(sound))
        if peak > 0:
            sound = sound / peak * 0.88

        self._activation_sound = sound  # float32 array, shape (n,)
        logger.info("Activation sound synthesised (%d samples).", len(sound))

    def play_activation_sound(self):
        """Play the activation chime via sounddevice and block until complete."""
        try:
            sd.play(self._activation_sound, samplerate=PLAYBACK_SR)
            sd.wait()
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

    # ── ElevenLabs TTS (PCM → sounddevice) ───────────────────────────────────

    def _speak_elevenlabs(self, text: str):
        """
        Request audio from ElevenLabs as raw 16-bit PCM at 22 050 Hz.
        Decode in-memory and play via sounddevice — no temp files, no external tools.
        """
        try:
            from elevenlabs import VoiceSettings  # type: ignore

            audio_stream = self._el_client.text_to_speech.convert(
                voice_id=self._voice_id,
                text=text,
                model_id="eleven_multilingual_v2",
                # pcm_22050 → signed 16-bit mono PCM, 22 050 Hz, no container
                output_format="pcm_22050",
                voice_settings=VoiceSettings(
                    stability=0.50,
                    similarity_boost=0.75,
                    style=0.10,
                    use_speaker_boost=True,
                ),
            )

            # Collect all PCM chunks into one bytes object
            pcm_bytes = b"".join(audio_stream)

            if not pcm_bytes:
                logger.warning("ElevenLabs returned empty audio — falling back.")
                if self._fallback_tts:
                    self._speak_pyttsx3(text)
                return

            # Decode int16 PCM → float32 in [-1, 1] for sounddevice
            audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
            audio_float = audio_int16.astype(np.float32) / 32768.0

            sd.play(audio_float, samplerate=PLAYBACK_SR)
            sd.wait()

        except Exception as exc:
            logger.error("ElevenLabs TTS error: %s — falling back.", exc)
            if self._fallback_tts:
                self._speak_pyttsx3(text)

    # ── pyttsx3 / SAPI5 fallback ──────────────────────────────────────────────

    def _speak_pyttsx3(self, text: str):
        try:
            self._fallback_tts.say(text)
            self._fallback_tts.runAndWait()
        except Exception as exc:
            logger.error("pyttsx3 TTS error: %s", exc)

    # ── Interrupt ─────────────────────────────────────────────────────────────

    def stop_speaking(self):
        """
        Interrupt any ongoing speech immediately.
        Safe to call from any thread.
        """
        try:
            sd.stop()
        except Exception:
            pass
        if self._fallback_tts:
            try:
                self._fallback_tts.stop()
            except Exception:
                pass

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self):
        """Stop any ongoing sounddevice playback."""
        try:
            sd.stop()
        except Exception:
            pass
