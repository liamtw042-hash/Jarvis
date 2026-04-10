#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║   JARVIS - Just A Rather Very Intelligent System v2.0   ║
║   Powered by Claude AI, ElevenLabs & OpenAI Whisper     ║
╚══════════════════════════════════════════════════════════╝

Entry point. Run this file to start JARVIS:
    python main.py
"""

import os
import sys
import signal
import logging
from pathlib import Path

# ── Ensure we're running in the project root ──────────────────────────────────
ROOT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT_DIR))
os.chdir(ROOT_DIR)

# Load .env before anything else
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

# ── Logging setup ─────────────────────────────────────────────────────────────
(ROOT_DIR / "logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(ROOT_DIR / "logs" / "jarvis.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("JARVIS")

# ── ASCII Banner ──────────────────────────────────────────────────────────────
BANNER = r"""
  ____           ____           ____           ____           ___ ____
 |    |         |    |         |    |         |    |         |   |    \
 |    |__       |    |__       |    |__       |    |__       |   |     \
 |       |      |       |      |       |      |       |      |   |      |
 | JARVIS|      | JARVIS|      | JARVIS|      | JARVIS|      |___|_____/

      ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
      ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
      ██║███████║██████╔╝██║   ██║██║███████╗
 ██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
 ╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
  ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝

       Just A Rather Very Intelligent System  v2.0
       ─────────────────────────────────────────────
       Powered by  Claude AI · ElevenLabs · Whisper
"""


def check_environment() -> bool:
    """Verify that all required API keys are present in .env."""
    required = {
        "ANTHROPIC_API_KEY": "Claude AI (brain)",
        "ELEVENLABS_API_KEY": "ElevenLabs TTS (voice)",
        "OPENAI_API_KEY": "OpenAI Whisper (speech-to-text)",
    }
    missing = {k: v for k, v in required.items() if not os.getenv(k)}

    if missing:
        print("\n[ERROR] Missing required API keys in your .env file:\n")
        for key, desc in missing.items():
            print(f"  ✗  {key}  —  {desc}")
        print("\nCopy .env.example to .env and fill in your keys.")
        print("See README.md for instructions on obtaining each key.\n")
        return False

    # Warn about optional keys that enable extra features
    optional = {
        "OPENWEATHER_API_KEY": "weather (Newcastle, AU)",
        "NEWS_API_KEY": "news headlines (falls back to BBC RSS)",
        "ALPHA_VANTAGE_API_KEY": "live forex rates",
        "EMAIL_ADDRESS": "email reading",
    }
    for key, desc in optional.items():
        if not os.getenv(key):
            logger.warning(f"Optional key {key} not set — {desc} disabled.")

    return True


def ensure_directories():
    """Create runtime directories if they don't exist."""
    for d in ("logs", "data", "sounds"):
        (ROOT_DIR / d).mkdir(exist_ok=True)


def main():
    print(BANNER)
    print("  Initialising JARVIS systems …\n")

    ensure_directories()

    if not check_environment():
        sys.exit(1)

    # Late import — modules may not be available until after env check
    from jarvis import JarvisAssistant

    jarvis = JarvisAssistant()

    # ── Graceful shutdown on Ctrl-C or kill ───────────────────────────────────
    def _shutdown(sig, frame):
        print("\n\n  Shutting down JARVIS. Goodbye, sir.\n")
        jarvis.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("JARVIS is online.")
    jarvis.start()


if __name__ == "__main__":
    main()
