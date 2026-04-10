"""
news.py — Live news headlines.

Primary:  NewsAPI.org (needs NEWS_API_KEY, free tier: 100 req/day)
Fallback: BBC News RSS feed (free, no key, always works)
"""

import logging
import os
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger("JARVIS.News")

NEWSAPI_URL   = "https://newsapi.org/v2/top-headlines"
BBC_RSS_URL   = "https://feeds.bbci.co.uk/news/rss.xml"
GUARDIAN_RSS  = "https://www.theguardian.com/world/rss"

# How many headlines to return
MAX_HEADLINES = 6


class NewsModule:
    """Fetches current news headlines."""

    def __init__(self):
        self._api_key = os.getenv("NEWS_API_KEY")
        # Country / category for NewsAPI
        self._country  = os.getenv("NEWS_COUNTRY", "gb")
        self._category = os.getenv("NEWS_CATEGORY", "general")

        if self._api_key:
            logger.info("News: NewsAPI.org (country=%s).", self._country)
        else:
            logger.info("News: BBC RSS fallback (no key required).")

    # ── Public interface ──────────────────────────────────────────────────────

    def get_headlines(self) -> list[str]:
        """Return a list of headline strings (titles only)."""
        headlines = []

        if self._api_key:
            headlines = self._fetch_newsapi()

        if not headlines:
            headlines = self._fetch_bbc_rss()

        if not headlines:
            headlines = self._fetch_guardian_rss()

        return headlines[:MAX_HEADLINES]

    # ── NewsAPI ───────────────────────────────────────────────────────────────

    def _fetch_newsapi(self) -> list[str]:
        try:
            resp = requests.get(
                NEWSAPI_URL,
                params={
                    "country":  self._country,
                    "category": self._category,
                    "pageSize": MAX_HEADLINES,
                    "apiKey":   self._api_key,
                },
                timeout=10,
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            titles   = [a["title"] for a in articles if a.get("title")]
            logger.info("NewsAPI: %d headlines.", len(titles))
            return titles
        except Exception as exc:
            logger.error("NewsAPI error: %s", exc)
            return []

    # ── BBC RSS ───────────────────────────────────────────────────────────────

    def _fetch_bbc_rss(self) -> list[str]:
        return self._parse_rss(BBC_RSS_URL, "BBC")

    def _fetch_guardian_rss(self) -> list[str]:
        return self._parse_rss(GUARDIAN_RSS, "Guardian")

    def _parse_rss(self, url: str, source: str) -> list[str]:
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "JARVIS/2.0"})
            resp.raise_for_status()
            root   = ET.fromstring(resp.content)
            titles = [item.findtext("title", default="").strip()
                      for item in root.findall(".//item")]
            titles = [t for t in titles if t]  # drop empty
            logger.info("%s RSS: %d headlines.", source, len(titles))
            return titles[:MAX_HEADLINES]
        except Exception as exc:
            logger.error("%s RSS error: %s", source, exc)
            return []
