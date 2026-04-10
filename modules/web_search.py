"""
web_search.py — DuckDuckGo web search.

Uses the duckduckgo-search library (no API key required).
Results are returned as a list of dicts and then summarised by ai_brain.
"""

import logging

logger = logging.getLogger("JARVIS.WebSearch")


class WebSearch:
    """Performs web searches via DuckDuckGo."""

    def __init__(self):
        try:
            from duckduckgo_search import DDGS  # type: ignore
            self._DDGS = DDGS
            logger.info("DuckDuckGo search ready.")
        except ImportError:
            self._DDGS = None
            logger.warning(
                "duckduckgo-search not installed.  "
                "Run: pip install duckduckgo-search"
            )

    def search(self, query: str, max_results: int = 6) -> list[dict]:
        """
        Search DuckDuckGo and return a list of result dicts.

        Each dict contains:
          title — page title
          body  — short snippet / description
          href  — URL
        """
        if not self._DDGS:
            return []

        try:
            with self._DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            logger.info("Search '%s' → %d results.", query, len(results))
            return results
        except Exception as exc:
            logger.error("DuckDuckGo search error: %s", exc)
            return []
