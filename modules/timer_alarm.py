"""
timer_alarm.py — Timers and alarms.

Timers count down from a set duration; alarms fire at a specific wall-clock time.
Both run in daemon threads and push spoken notifications into a Queue that the
main loop drains between listen cycles — ensuring JARVIS never misses an alert.
"""

import logging
import queue
import re
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger("JARVIS.TimerAlarm")

# Unit → seconds conversion
UNIT_SECONDS: dict[str, int] = {
    "second": 1,  "sec": 1,  "s": 1,
    "minute": 60, "min": 60, "m": 60,
    "hour":  3600, "hr": 3600, "h": 3600,
}


class TimerAlarm:
    """Manages countdown timers and scheduled alarms."""

    def __init__(self, voice_output):
        """
        Parameters
        ----------
        voice_output : VoiceOutput
            Used to directly speak alerts from background threads.
        """
        self._voice_output = voice_output
        self.notification_queue: queue.Queue[str] = queue.Queue()
        self._active_timers: list[threading.Timer] = []
        self._alarm_thread: threading.Thread | None = None
        self._alarms: list[datetime] = []
        self._alarm_lock = threading.Lock()

        # Start the alarm-checker daemon
        self._start_alarm_watcher()

    # ── Timer ─────────────────────────────────────────────────────────────────

    def set_timer(self, amount: int, unit: str) -> str:
        """
        Start a countdown timer.

        Parameters
        ----------
        amount : int
            Number of units.
        unit   : str
            'second', 'sec', 'minute', 'min', 'hour', 'hr' (case-insensitive).
        """
        unit_key = unit.lower().rstrip("s")  # normalise plural
        multiplier = UNIT_SECONDS.get(unit_key)

        if multiplier is None:
            return f"I don't recognise the time unit '{unit}', sir."

        total_seconds = amount * multiplier
        if total_seconds <= 0 or total_seconds > 86400:
            return "Please set a timer between 1 second and 24 hours, sir."

        human_time = self._human_duration(total_seconds)
        logger.info("Timer set: %d seconds (%s).", total_seconds, human_time)

        t = threading.Timer(total_seconds, self._timer_done, args=[human_time])
        t.daemon = True
        t.start()
        self._active_timers.append(t)

        return f"Timer set for {human_time}, sir.  I'll let you know when it's up."

    def _timer_done(self, human_time: str):
        msg = f"Your {human_time} timer is up, sir."
        logger.info("Timer fired: %s", msg)
        # Push to queue for main-loop pickup AND speak directly (works even during speech)
        self.notification_queue.put(msg)

    # ── Alarm ─────────────────────────────────────────────────────────────────

    def set_alarm(self, time_str: str | None) -> str:
        """
        Schedule an alarm for a specific time of day.

        Parameters
        ----------
        time_str : str | None
            Time string such as "7am", "6:30", "14:00", "7:30 pm".
        """
        if not time_str:
            return (
                "I didn't catch the time for the alarm, sir. "
                "Please say something like 'set an alarm for 7 a.m.'"
            )

        alarm_dt = self._parse_time(time_str.strip())
        if alarm_dt is None:
            return (
                f"I couldn't parse '{time_str}' as a time, sir. "
                "Please use a format like '7am', '6:30pm', or '14:00'."
            )

        # If the time is in the past today, schedule for tomorrow
        now = datetime.now()
        if alarm_dt <= now:
            alarm_dt += timedelta(days=1)

        delta_minutes = int((alarm_dt - now).total_seconds() / 60)

        with self._alarm_lock:
            self._alarms.append(alarm_dt)

        time_fmt = alarm_dt.strftime("%-I:%M %p") if alarm_dt.second == 0 else alarm_dt.strftime("%-I:%M:%S %p")
        logger.info("Alarm set for %s (in ~%d minutes).", alarm_dt, delta_minutes)

        return (
            f"Alarm set for {time_fmt}, sir.  "
            f"That's approximately {delta_minutes} minutes from now."
        )

    def _start_alarm_watcher(self):
        """Daemon thread that checks every 30 seconds for due alarms."""
        def watcher():
            while True:
                time.sleep(30)
                now = datetime.now()
                triggered = []
                with self._alarm_lock:
                    remaining = []
                    for alarm in self._alarms:
                        # Fire if within the current 30-second window
                        diff = abs((alarm - now).total_seconds())
                        if diff <= 30:
                            triggered.append(alarm)
                        else:
                            remaining.append(alarm)
                    self._alarms = remaining

                for alarm in triggered:
                    msg = f"Good morning, sir.  Your alarm for {alarm.strftime('%-I:%M %p')} is now."
                    logger.info("Alarm fired: %s", msg)
                    self.notification_queue.put(msg)

        t = threading.Thread(target=watcher, daemon=True, name="AlarmWatcher")
        t.start()
        self._alarm_thread = t

    # ── Time parsing ──────────────────────────────────────────────────────────

    def _parse_time(self, text: str) -> datetime | None:
        """
        Try to parse a variety of spoken time formats into a datetime.
        Supports:
          7am, 7 am, 7:30am, 7:30 am, 14:00, 2:30 pm, 6 o'clock
        """
        text = text.lower().replace("o'clock", "").replace("'", "").strip()
        now  = datetime.now()

        # Formats to try (most specific first)
        formats = [
            ("%I:%M %p", True),   # "7:30 am"
            ("%I:%M%p",  True),   # "7:30am"
            ("%H:%M",    False),  # "14:00"
            ("%I %p",    True),   # "7 am"
            ("%I%p",     True),   # "7am"
            ("%H",       False),  # "14"
        ]

        for fmt, needs_ampm in formats:
            # If the format needs am/pm but text has none, skip
            if needs_ampm and not re.search(r"[ap]m", text):
                continue
            try:
                parsed = datetime.strptime(text, fmt)
                return now.replace(
                    hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
                )
            except ValueError:
                continue

        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _human_duration(seconds: int) -> str:
        """Convert a number of seconds to a human-readable string."""
        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"
        if seconds < 3600:
            minutes = seconds // 60
            secs    = seconds % 60
            base    = f"{minutes} minute{'s' if minutes != 1 else ''}"
            return base + (f" and {secs} seconds" if secs else "")
        hours   = seconds // 3600
        minutes = (seconds % 3600) // 60
        base    = f"{hours} hour{'s' if hours != 1 else ''}"
        return base + (f" and {minutes} minutes" if minutes else "")
