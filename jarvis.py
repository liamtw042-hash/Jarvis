"""
jarvis.py — Core orchestrator.

Ties together every subsystem:
  voice_input  →  wake-word detection & Whisper STT
  voice_output →  ElevenLabs TTS & activation chime
  ai_brain     →  Claude conversation + intent routing
  + all specialised modules (weather, forex, timers …)
"""

import logging
import queue
import re
import time

logger = logging.getLogger("JARVIS.Core")


class JarvisAssistant:
    """Top-level coordinator.  One instance per session."""

    # How long (seconds) JARVIS stays in conversation mode after each response
    # before requiring the wake word again.
    CONVERSATION_TIMEOUT = 12

    def __init__(self):
        logger.info("Loading JARVIS modules …")
        self._load_modules()
        logger.info("All modules ready.")

    # ── Module initialisation ─────────────────────────────────────────────────

    def _load_modules(self):
        """Initialise every subsystem.  Failures are logged but don't crash."""
        from modules.voice_input import VoiceInput
        from modules.voice_output import VoiceOutput
        from modules.ai_brain import AIBrain
        from modules.app_control import AppControl
        from modules.web_search import WebSearch
        from modules.weather import WeatherModule
        from modules.forex import ForexModule
        from modules.memory import MemoryModule
        from modules.news import NewsModule
        from modules.system_control import SystemControl
        from modules.timer_alarm import TimerAlarm
        from modules.email_reader import EmailReader

        self.voice_output = VoiceOutput()
        self.voice_input = VoiceInput()
        self.ai_brain = AIBrain()
        self.app_control = AppControl()
        self.web_search = WebSearch()
        self.weather = WeatherModule()
        self.forex = ForexModule()
        self.memory = MemoryModule()
        self.news = NewsModule()
        self.system_control = SystemControl()

        # TimerAlarm gets a reference to voice_output so it can announce alarms
        self.timer_alarm = TimerAlarm(self.voice_output)

        self.email_reader = EmailReader()

        self.running = False

    # ── Main loop ─────────────────────────────────────────────────────────────

    def start(self):
        """Block and run the main listen → respond loop."""
        self.running = True
        print("\n  JARVIS is online.  Say  'Hey Jarvis'  to activate.\n")
        print("  (Press Ctrl-C to quit)\n")
        print("  " + "─" * 56)

        in_conversation = False
        last_response_time = 0.0

        while self.running:
            try:
                # ── Check for pending timer/alarm notifications ────────────
                self._flush_notifications()

                # ── Decide whether to require wake word ───────────────────
                elapsed = time.time() - last_response_time
                still_active = in_conversation and elapsed < self.CONVERSATION_TIMEOUT

                if still_active:
                    # Already mid-conversation — listen directly
                    command_audio = self.voice_input.listen_for_command()
                    if command_audio is None:
                        in_conversation = False
                        print("\n  (Conversation mode ended — say 'Hey Jarvis' to restart)\n")
                        continue
                    command_text = self.voice_input.transcribe(command_audio)
                else:
                    # Wait for wake word
                    detected, inline_cmd = self.voice_input.listen_for_wake_word()
                    if not detected:
                        continue

                    logger.info("Wake word detected.")
                    self.voice_output.play_activation_sound()

                    # User may have spoken the command in the same breath
                    if inline_cmd and len(inline_cmd) > 2:
                        command_text = inline_cmd
                    else:
                        command_audio = self.voice_input.listen_for_command()
                        if command_audio is None:
                            continue
                        command_text = self.voice_input.transcribe(command_audio)

                # ── Bail if nothing useful was heard ──────────────────────
                if not command_text or len(command_text.strip()) < 2:
                    self.voice_output.speak(
                        "I didn't quite catch that, sir.  Could you repeat?"
                    )
                    continue

                print(f"\n  You    : {command_text}")

                # ── Route and respond ─────────────────────────────────────
                response = self.process_command(command_text)
                print(f"  JARVIS : {response}\n")
                self.voice_output.speak(response)

                in_conversation = True
                last_response_time = time.time()

            except KeyboardInterrupt:
                break
            except Exception as exc:
                logger.error("Unhandled error in main loop: %s", exc, exc_info=True)
                # Never crash — just keep listening
                time.sleep(0.5)

    # ── Command processing ────────────────────────────────────────────────────

    def process_command(self, text: str) -> str:
        """Detect intent, dispatch to module, return a speakable response."""
        self.ai_brain.add_user_message(text)

        intent, params = self._detect_intent(text.lower().strip())
        logger.info("Intent detected: %s  params=%s", intent, params)

        try:
            response = self._handle_intent(intent, params, text)
        except Exception as exc:
            logger.error("Error handling intent '%s': %s", intent, exc, exc_info=True)
            response = (
                "I ran into a bit of trouble with that request, sir.  "
                "Please try again in a moment."
            )

        self.ai_brain.add_assistant_message(response)
        return response

    # ── Intent detection ──────────────────────────────────────────────────────

    def _detect_intent(self, text: str):
        """
        Fast keyword/regex routing.
        Returns (intent_name, params_dict).
        Falls through to 'general' for anything Claude should answer directly.
        """

        # ── Time ──────────────────────────────────────────────────────────────
        if re.search(r"\b(what(?:'s| is)(?: the)? time|current time|time is it)\b", text):
            return "time", {}

        # ── Date / Day ────────────────────────────────────────────────────────
        if re.search(
            r"\b(what(?:'s| is)(?: the)? date|today(?:'s date)?|what day|day is it)\b",
            text,
        ):
            return "date", {}

        # ── Weather ───────────────────────────────────────────────────────────
        if re.search(r"\b(weather|temperature|forecast|rain|sunny|humid|wind)\b", text):
            return "weather", {}

        # ── Timer  (e.g. "set a 5 minute timer" / "timer for 30 seconds") ────
        m = re.search(
            r"(?:set\s+(?:a\s+)?)?(\d+)\s*(second|sec|minute|min|hour|hr)s?"
            r"(?:\s+timer)?|timer\s+(?:for\s+)?(\d+)\s*(second|sec|minute|min|hour|hr)s?",
            text,
        )
        if m and re.search(r"\btimer\b", text):
            num   = int(m.group(1) or m.group(3))
            unit  = (m.group(2) or m.group(4)).lower()
            return "timer", {"amount": num, "unit": unit}

        # ── Alarm  (e.g. "set an alarm for 7am" / "wake me at 6:30") ─────────
        if re.search(r"\b(alarm|wake me)\b", text):
            am = re.search(
                r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", text, re.IGNORECASE
            )
            return "alarm", {"time_str": am.group(1) if am else None}

        # ── Volume ────────────────────────────────────────────────────────────
        if re.search(r"\b(volume|louder|quieter|mute|unmute|turn up|turn down|sound)\b", text):
            return "volume", {"raw": text}

        # ── Open app / website ────────────────────────────────────────────────
        m = re.search(r"\b(?:open|launch|start|go to|navigate to|pull up)\s+(.+)", text)
        if m:
            return "open", {"target": m.group(1).strip()}

        # ── Web search ────────────────────────────────────────────────────────
        m = re.search(
            r"(?:search(?:\s+for)?|google(?:\s+for)?|look up|find(?:\s+info(?:rmation)?"
            r"(?:\s+(?:about|on))?)?)\s+(.+)",
            text,
        )
        if m:
            return "search", {"query": m.group(1).strip()}

        # ── Forex ─────────────────────────────────────────────────────────────
        if re.search(
            r"\b(forex|exchange rate|gbp.?usd|eur.?usd|pound|euro|currency rate)\b",
            text,
        ):
            return "forex", {}

        # ── News ──────────────────────────────────────────────────────────────
        if re.search(r"\b(news|headlines|latest|what.s happening|current events)\b", text):
            return "news", {}

        # ── Email ─────────────────────────────────────────────────────────────
        if re.search(r"\b(email|emails|inbox|mail|messages)\b", text):
            return "email", {}

        # ── Remember something ────────────────────────────────────────────────
        m = re.search(r"(?:remember|note down|don.t forget|make a note)\s+(?:that\s+)?(.+)", text)
        if m:
            return "remember", {"content": m.group(1).strip()}

        # ── Recall memory ─────────────────────────────────────────────────────
        if re.search(r"(?:what did i|what do you remember|recall|remind me)", text):
            return "recall", {}

        # ── Joke ──────────────────────────────────────────────────────────────
        if re.search(r"\b(joke|make me laugh|something funny|humou?r)\b", text):
            return "joke", {}

        # ── Calculator ────────────────────────────────────────────────────────
        m = re.search(r"(?:calculate|compute|what(?:'s| is)\s+)(.+)", text)
        if m and re.search(r"[\d+\-*/^%()]", m.group(1)):
            return "calculate", {"expression": m.group(1).strip()}

        # ── Stop / dismiss ────────────────────────────────────────────────────
        if re.search(r"\b(stop|cancel|never mind|nevermind|bye|goodbye|that.s all)\b", text):
            return "stop", {}

        # ── Fallback → let Claude answer ──────────────────────────────────────
        return "general", {}

    # ── Intent handlers ───────────────────────────────────────────────────────

    def _handle_intent(self, intent: str, params: dict, original: str) -> str:
        handlers = {
            "time":      lambda: self.system_control.get_time(),
            "date":      lambda: self.system_control.get_date(),
            "weather":   lambda: self.weather.get_weather(),
            "timer":     lambda: self.timer_alarm.set_timer(params["amount"], params["unit"]),
            "alarm":     lambda: self.timer_alarm.set_alarm(params.get("time_str")),
            "volume":    lambda: self.system_control.control_volume(params["raw"]),
            "open":      lambda: self.app_control.open_target(params["target"]),
            "search":    lambda: self._handle_search(params["query"]),
            "forex":     lambda: self.forex.get_rates(),
            "news":      lambda: self._handle_news(),
            "email":     lambda: self._handle_email(),
            "remember":  lambda: self.memory.remember(params["content"]),
            "recall":    lambda: self._handle_recall(),
            "joke":      lambda: self.ai_brain.tell_joke(),
            "calculate": lambda: self.system_control.calculate(params["expression"]),
            "stop":      lambda: "Of course, sir.  I'm standing by.",
            "general":   lambda: self.ai_brain.chat(original),
        }
        handler = handlers.get(intent, handlers["general"])
        return handler()

    def _handle_search(self, query: str) -> str:
        results = self.web_search.search(query)
        return self.ai_brain.summarise_search_results(query, results)

    def _handle_news(self) -> str:
        headlines = self.news.get_headlines()
        return self.ai_brain.present_news(headlines)

    def _handle_email(self) -> str:
        emails = self.email_reader.get_recent_emails()
        return self.ai_brain.summarise_emails(emails)

    def _handle_recall(self) -> str:
        memories = self.memory.recall_all()
        return self.ai_brain.present_memories(memories)

    # ── Timer / alarm notifications ───────────────────────────────────────────

    def _flush_notifications(self):
        """Speak any pending timer/alarm alerts without blocking the loop."""
        while not self.timer_alarm.notification_queue.empty():
            try:
                msg = self.timer_alarm.notification_queue.get_nowait()
                print(f"\n  JARVIS : {msg}\n")
                self.voice_output.speak(msg)
            except queue.Empty:
                break

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def shutdown(self):
        self.running = False
        try:
            self.voice_output.cleanup()
        except Exception:
            pass
        try:
            self.memory.save()
        except Exception:
            pass
        logger.info("JARVIS shutdown complete.")
