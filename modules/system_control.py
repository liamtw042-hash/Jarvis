"""
system_control.py — System information and control.

Features
────────
• Time / date / day queries
• System volume control (Windows, via pycaw)
• Safe mathematical expression evaluator
• Basic system info (battery, uptime)
"""

import ast
import logging
import operator
import re
from datetime import datetime

logger = logging.getLogger("JARVIS.SystemControl")

# ── Safe maths ────────────────────────────────────────────────────────────────
# Only these AST node types are allowed — no function calls, no imports, etc.
_ALLOWED_OPS = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
    ast.Mod:  operator.mod,
    ast.Pow:  operator.pow,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: lambda x: x,
}


def _safe_eval(node):
    """Recursively evaluate a safe subset of Python AST math nodes."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        left  = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return _ALLOWED_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


class SystemControl:
    """Handles time/date queries, volume control, and calculations."""

    def __init__(self):
        self._volume_interface = None
        self._init_volume()

    # ── Volume ────────────────────────────────────────────────────────────────

    def _init_volume(self):
        """Initialise Windows pycaw audio interface."""
        try:
            from ctypes import cast, POINTER           # type: ignore
            from comtypes import CLSCTX_ALL            # type: ignore
            from pycaw.pycaw import (                  # type: ignore
                AudioUtilities, IAudioEndpointVolume
            )
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None
            )
            self._volume_interface = cast(interface, POINTER(IAudioEndpointVolume))
            logger.info("Volume control ready (pycaw).")
        except Exception as exc:
            logger.warning("Volume control unavailable: %s", exc)

    def control_volume(self, raw_command: str) -> str:
        """
        Adjust or mute system volume based on a natural-language command.

        Recognises:
          "set volume to 50%", "volume 70", "turn up the volume",
          "louder", "quieter", "mute", "unmute"
        """
        cmd = raw_command.lower()

        # Mute / unmute
        if "mute" in cmd and "unmute" not in cmd:
            return self._set_mute(True)
        if "unmute" in cmd:
            return self._set_mute(False)

        # Specific percentage
        m = re.search(r"(\d{1,3})\s*%?", cmd)
        if m:
            level = max(0, min(100, int(m.group(1))))
            return self._set_volume(level)

        # Relative adjustments
        current = self._get_volume()
        if current is None:
            return "Volume control isn't available on this system, sir."

        if re.search(r"\b(louder|turn up|increase|up)\b", cmd):
            return self._set_volume(min(100, current + 15))
        if re.search(r"\b(quieter|turn down|decrease|down|lower)\b", cmd):
            return self._set_volume(max(0, current - 15))

        # Report current volume
        return f"The volume is currently at {current} percent, sir."

    def _get_volume(self) -> int | None:
        if self._volume_interface is None:
            return None
        try:
            return round(self._volume_interface.GetMasterVolumeLevelScalar() * 100)
        except Exception:
            return None

    def _set_volume(self, level: int) -> str:
        if self._volume_interface is None:
            return "Volume control isn't available on this system, sir."
        try:
            self._volume_interface.SetMasterVolumeLevelScalar(level / 100, None)
            logger.info("Volume set to %d%%.", level)
            return f"Volume set to {level} percent, sir."
        except Exception as exc:
            logger.error("Failed to set volume: %s", exc)
            return "I had trouble adjusting the volume, sir."

    def _set_mute(self, mute: bool) -> str:
        if self._volume_interface is None:
            return "Volume control isn't available on this system, sir."
        try:
            self._volume_interface.SetMute(1 if mute else 0, None)
            state = "muted" if mute else "unmuted"
            logger.info("System audio %s.", state)
            return f"System audio {state}, sir."
        except Exception as exc:
            logger.error("Failed to mute/unmute: %s", exc)
            return "I couldn't change the mute state, sir."

    # ── Time / Date ───────────────────────────────────────────────────────────

    def get_time(self) -> str:
        """Return the current time as a spoken string."""
        now = datetime.now()
        # e.g. "It's 3:47 in the afternoon, sir."
        hour   = now.hour
        minute = now.minute
        period = "in the morning" if hour < 12 else ("in the afternoon" if hour < 18 else "in the evening")

        if minute == 0:
            time_str = f"{now.strftime('%I').lstrip('0')} o'clock {period}"
        elif minute == 30:
            time_str = f"half past {now.strftime('%I').lstrip('0')} {period}"
        elif minute == 15:
            time_str = f"quarter past {now.strftime('%I').lstrip('0')} {period}"
        elif minute == 45:
            next_hour = (hour % 12) + 1
            time_str = f"quarter to {next_hour} {period}"
        else:
            time_str = now.strftime("%-I:%M %p").lower()

        return f"It's {time_str}, sir."

    def get_date(self) -> str:
        """Return the current date as a spoken string."""
        now  = datetime.now()
        day  = now.strftime("%A")       # Monday
        date = now.strftime("%-d")      # 7
        month= now.strftime("%B")       # April
        year = now.strftime("%Y")       # 2025

        suffix = self._ordinal_suffix(int(date))
        return f"Today is {day}, the {date}{suffix} of {month}, {year}, sir."

    @staticmethod
    def _ordinal_suffix(n: int) -> str:
        if 11 <= n % 100 <= 13:
            return "th"
        return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")

    # ── Calculator ────────────────────────────────────────────────────────────

    def calculate(self, expression: str) -> str:
        """
        Safely evaluate a mathematical expression and return the result.
        Supports: +, -, *, /, //, %, ** and parentheses.
        """
        # Normalise spoken/written math
        expr = expression.lower()
        expr = expr.replace("×", "*").replace("x", "*").replace("÷", "/")
        expr = expr.replace("^", "**").replace("squared", "**2").replace("cubed", "**3")
        expr = re.sub(r"[^0-9+\-*/.%^()\s]", "", expr).strip()

        if not expr:
            return "I couldn't parse that expression, sir.  Please use digits and operators."

        try:
            tree   = ast.parse(expr, mode="eval")
            result = _safe_eval(tree.body)

            # Format nicely
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            formatted = f"{result:,}" if isinstance(result, int) else f"{result:,.6g}"
            logger.info("Calculated '%s' = %s", expr, formatted)
            return f"The answer is {formatted}, sir."

        except ZeroDivisionError:
            return "That expression involves a division by zero, sir — mathematically undefined."
        except Exception as exc:
            logger.warning("Calculation error for '%s': %s", expr, exc)
            return (
                "I wasn't able to calculate that, sir.  "
                "Please phrase it using numbers and standard operators."
            )
