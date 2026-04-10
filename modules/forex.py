"""
forex.py — Live forex rates for GBP/USD and EUR/USD.

Primary:  Alpha Vantage API  (needs ALPHA_VANTAGE_API_KEY, free tier: 25 req/day)
Fallback: Open Exchange Rates via exchangerate.host (free, no key)
"""

import logging
import os
from datetime import datetime

import requests

logger = logging.getLogger("JARVIS.Forex")

ALPHA_VANTAGE_URL  = "https://www.alphavantage.co/query"
EXCHANGE_RATE_URL  = "https://open.er-api.com/v6/latest/{base}"

# Pairs to report
PAIRS = [
    ("GBP", "USD"),
    ("EUR", "USD"),
]


class ForexModule:
    """Fetches and narrates live forex rates."""

    def __init__(self):
        self._alpha_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        if self._alpha_key:
            logger.info("Forex: Alpha Vantage API.")
        else:
            logger.info("Forex: exchangerate.host fallback (free).")

    # ── Public interface ──────────────────────────────────────────────────────

    def get_rates(self) -> str:
        """Return a spoken summary of GBP/USD and EUR/USD."""
        rates = {}
        for base, quote in PAIRS:
            rate = self._fetch_rate(base, quote)
            if rate is not None:
                rates[f"{base}/{quote}"] = rate

        if not rates:
            return (
                "I'm unable to retrieve forex rates at the moment, sir.  "
                "Please check your internet connection."
            )

        lines = []
        for pair, rate in rates.items():
            lines.append(f"{pair} is trading at {rate:.4f}")

        timestamp = datetime.now().strftime("%I:%M %p")
        return (
            "Here are the latest exchange rates as of "
            + timestamp
            + ": "
            + ", and ".join(lines)
            + "."
        )

    # ── Alpha Vantage ─────────────────────────────────────────────────────────

    def _fetch_rate_alpha(self, base: str, quote: str) -> float | None:
        try:
            resp = requests.get(
                ALPHA_VANTAGE_URL,
                params={
                    "function":      "CURRENCY_EXCHANGE_RATE",
                    "from_currency": base,
                    "to_currency":   quote,
                    "apikey":        self._alpha_key,
                },
                timeout=10,
            )
            resp.raise_for_status()
            j    = resp.json()
            data = j.get("Realtime Currency Exchange Rate", {})
            rate = data.get("5. Exchange Rate")
            if rate:
                return float(rate)
        except Exception as exc:
            logger.error("Alpha Vantage error (%s/%s): %s", base, quote, exc)
        return None

    # ── exchangerate.host fallback ────────────────────────────────────────────

    def _fetch_rate_fallback(self, base: str, quote: str) -> float | None:
        try:
            url  = EXCHANGE_RATE_URL.format(base=base)
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            j    = resp.json()
            if j.get("result") == "success":
                return j["rates"].get(quote)
        except Exception as exc:
            logger.error("exchangerate fallback error (%s/%s): %s", base, quote, exc)
        return None

    # ── Unified fetch ─────────────────────────────────────────────────────────

    def _fetch_rate(self, base: str, quote: str) -> float | None:
        if self._alpha_key:
            rate = self._fetch_rate_alpha(base, quote)
            if rate is not None:
                return rate
            logger.warning("Alpha Vantage failed — trying fallback.")
        return self._fetch_rate_fallback(base, quote)
