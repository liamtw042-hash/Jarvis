"""
memory.py — Persistent cross-session memory.

JARVIS can store arbitrary facts the user tells it and recall them later.
Data is persisted to data/memory.json between sessions.

Example commands:
  "Remember that my wife's name is Sarah"
  "Note that my car registration is AB12 CDE"
  "What do you remember?"
  "Remind me of my notes"
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("JARVIS.Memory")

MEMORY_FILE = Path("data") / "memory.json"


class MemoryModule:
    """Stores and retrieves named facts for the user."""

    def __init__(self):
        Path("data").mkdir(exist_ok=True)
        self._memories: dict[str, dict] = self._load()
        logger.info("Memory loaded: %d item(s).", len(self._memories))

    # ── Public interface ──────────────────────────────────────────────────────

    def remember(self, content: str) -> str:
        """
        Parse a natural-language statement and store the key fact.

        Examples of content strings:
          "my wife's name is Sarah"
          "the office Wi-Fi password is hunter2"
          "I prefer dark roast coffee"
        """
        content = content.strip(" .")

        # Attempt to split "X is Y" / "X: Y" / "X = Y"
        key, value = self._parse_key_value(content)

        timestamp = datetime.now().isoformat(timespec="seconds")
        self._memories[key] = {"value": value, "stored_at": timestamp}
        self.save()

        logger.info("Memory stored — '%s': '%s'", key, value)
        return f"Noted, sir.  I'll remember that {key} is {value}."

    def recall_all(self) -> dict:
        """Return all stored memories as a plain dict {key: value}."""
        return {k: v["value"] for k, v in self._memories.items()}

    def recall(self, key: str) -> str | None:
        """Return a specific memory value, or None if not found."""
        entry = self._memories.get(key.lower())
        return entry["value"] if entry else None

    def forget(self, key: str) -> str:
        """Remove a specific memory entry."""
        if key in self._memories:
            del self._memories[key]
            self.save()
            return f"I've forgotten {key}, sir."
        return f"I don't have anything stored under '{key}', sir."

    def save(self):
        """Persist memories to disk."""
        try:
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self._memories, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("Failed to save memory: %s", exc)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if MEMORY_FILE.exists():
            try:
                with open(MEMORY_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as exc:
                logger.warning("Could not load memory file: %s — starting fresh.", exc)
        return {}

    @staticmethod
    def _parse_key_value(content: str) -> tuple[str, str]:
        """
        Extract (key, value) from a natural statement.

        Handles:
          "my PIN is 1234"          → ("my PIN", "1234")
          "the answer = 42"         → ("the answer", "42")
          "Sarah's birthday: 12 May" → ("Sarah's birthday", "12 May")
          "I love jazz music"       → ("preference", "I love jazz music")
        """
        content_lower = content.lower()

        # Pattern: "X is Y" / "X are Y"
        m = re.match(r"^(.+?)\s+(?:is|are)\s+(.+)$", content, re.IGNORECASE)
        if m:
            return m.group(1).strip().lower(), m.group(2).strip()

        # Pattern: "X: Y" / "X = Y" / "X - Y"
        m = re.match(r"^(.+?)\s*[:=\-]\s*(.+)$", content)
        if m:
            return m.group(1).strip().lower(), m.group(2).strip()

        # No clear key/value — store the whole thing under a timestamp key
        key = f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return key, content
