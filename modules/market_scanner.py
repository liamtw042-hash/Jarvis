"""
market_scanner.py — Automated forex trading setup scanner.

Strategy (applied per pair, every SCAN_INTERVAL_MINUTES)
──────────────────────────────────────────────────────────
1. 4H chart  — determine trend via 50 EMA vs 200 EMA
                  50 EMA > 200 EMA → bullish trend
                  50 EMA < 200 EMA → bearish trend
2. 4H chart  — locate Fair Value Gaps (FVGs) aligned with the trend
                  Bullish FVG: candle[n-2].high < candle[n].low   (upside gap)
                  Bearish FVG: candle[n-2].low  > candle[n].high  (downside gap)
3. Price     — check whether the current price has pulled back into a 4H FVG
4. 1H chart  — confirm with directional candle structure
                  Bullish: ≥ 2 of last 3 candles are bullish AND last is bullish
                  Bearish: ≥ 2 of last 3 candles are bearish AND last is bearish

When all four conditions align a setup alert is pushed to notification_queue
and JARVIS announces it unprompted. The voice command "any setups" triggers
an immediate on-demand scan.

Data sources
────────────
Primary:  yfinance (free, no API key, Yahoo Finance forex feed)
Fallback: Alpha Vantage FX_INTRADAY (needs ALPHA_VANTAGE_API_KEY in .env)
"""

import logging
import os
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger("JARVIS.MarketScanner")

# ── Configuration ──────────────────────────────────────────────────────────────

PAIRS = ["GBPUSD", "EURUSD", "AUDUSD", "USDJPY"]

# Background scan frequency
SCAN_INTERVAL_MINUTES = 15

# Suppress repeated alerts for the same setup within this window
ALERT_COOLDOWN_HOURS = 4

# How many 4H candles back to search for valid FVGs
FVG_LOOKBACK = 20

# Minimum EMA history needed (must have ≥ this many 4H candles)
MIN_CANDLES = 210

# yfinance ticker symbols (Yahoo Finance format)
YF_TICKERS = {
    "GBPUSD": "GBPUSD=X",
    "EURUSD": "EURUSD=X",
    "AUDUSD": "AUDUSD=X",
    "USDJPY": "USDJPY=X",
}

# Alpha Vantage from/to symbols
AV_SYMBOLS = {
    "GBPUSD": ("GBP", "USD"),
    "EURUSD": ("EUR", "USD"),
    "AUDUSD": ("AUD", "USD"),
    "USDJPY": ("USD", "JPY"),
}

# Decimal places for price display (JPY pairs use 2, everything else 4/5)
PRICE_DECIMALS = {
    "USDJPY": 2,
}


class MarketScanner:
    """
    Scans forex pairs for ICT-style FVG pullback setups and alerts via
    JARVIS's voice output.
    """

    def __init__(self, voice_output):
        """
        Parameters
        ----------
        voice_output : VoiceOutput
            Used to speak market alerts from the background thread.
        """
        self._voice_output = voice_output
        self.notification_queue: queue.Queue[str] = queue.Queue()

        # Cooldown tracker: {(pair, direction): datetime_last_alerted}
        self._last_alerted: dict[tuple, datetime] = {}

        # Prefer yfinance; fall back to Alpha Vantage if unavailable
        self._data_source = self._select_data_source()

        # Start background scanner daemon
        self._start_scanner()
        logger.info(
            "Market scanner ready — scanning %s every %d min via %s.",
            ", ".join(PAIRS), SCAN_INTERVAL_MINUTES, self._data_source,
        )

    # ── Data source selection ──────────────────────────────────────────────────

    def _select_data_source(self) -> str:
        try:
            import yfinance  # type: ignore  # noqa: F401
            return "yfinance"
        except ImportError:
            pass

        if os.getenv("ALPHA_VANTAGE_API_KEY"):
            return "alphavantage"

        logger.warning(
            "Neither yfinance nor ALPHA_VANTAGE_API_KEY available. "
            "Install yfinance: pip install yfinance"
        )
        return "none"

    # ── Data fetching ──────────────────────────────────────────────────────────

    def _get_1h_candles(self, pair: str) -> pd.DataFrame:
        """
        Fetch ~60 days of 1-hour OHLC data for a forex pair.
        Returns a DataFrame with columns [Open, High, Low, Close], UTC index.
        """
        if self._data_source == "yfinance":
            return self._fetch_yfinance(pair)
        elif self._data_source == "alphavantage":
            return self._fetch_alphavantage(pair)
        else:
            raise RuntimeError("No data source configured.")

    def _fetch_yfinance(self, pair: str) -> pd.DataFrame:
        import yfinance as yf  # type: ignore

        ticker = YF_TICKERS[pair]
        df = yf.download(
            ticker,
            interval="1h",
            period="60d",
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            raise ValueError(f"yfinance returned no data for {pair}.")

        # Flatten MultiIndex columns that appear when downloading a single ticker
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df[["Open", "High", "Low", "Close"]].copy().dropna()

        # Normalise index to UTC
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        return df

    def _fetch_alphavantage(self, pair: str) -> pd.DataFrame:
        api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        from_sym, to_sym = AV_SYMBOLS[pair]

        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function":    "FX_INTRADAY",
                "from_symbol": from_sym,
                "to_symbol":   to_sym,
                "interval":    "60min",
                "outputsize":  "full",
                "apikey":      api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        key = "Time Series FX (60min)"
        if key not in data:
            msg = data.get("Information") or data.get("Note") or str(list(data.keys()))
            raise ValueError(f"Alpha Vantage error for {pair}: {msg}")

        df = pd.DataFrame.from_dict(data[key], orient="index")
        df.index = pd.to_datetime(df.index, utc=True)
        df.sort_index(inplace=True)
        df.columns = ["Open", "High", "Low", "Close"]
        df = df.apply(pd.to_numeric)
        return df.dropna()

    # ── Timeframe resampling ───────────────────────────────────────────────────

    @staticmethod
    def _resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
        """Aggregate 1H candles into 4H candles aligned to 00:00 UTC."""
        df_4h = df_1h.resample("4h", origin="start_day").agg(
            Open=("Open", "first"),
            High=("High", "max"),
            Low=("Low", "min"),
            Close=("Close", "last"),
        ).dropna()
        return df_4h

    # ── Indicators ────────────────────────────────────────────────────────────

    @staticmethod
    def _ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    # ── Fair Value Gap detection ───────────────────────────────────────────────

    @staticmethod
    def _find_fvgs(df: pd.DataFrame, direction: str) -> list[dict]:
        """
        Scan the last FVG_LOOKBACK candles for Fair Value Gaps.

        Bullish FVG (upside imbalance):
            candle[i-2].High  <  candle[i].Low
            Zone: bottom = candle[i-2].High, top = candle[i].Low

        Bearish FVG (downside imbalance):
            candle[i-2].Low   >  candle[i].High
            Zone: bottom = candle[i].High,   top = candle[i-2].Low
        """
        # Only search the recent window (+2 for the 3-candle pattern boundary)
        window = df.tail(FVG_LOOKBACK + 2)
        fvgs = []

        for i in range(2, len(window)):
            c0 = window.iloc[i - 2]   # oldest of the trio
            c2 = window.iloc[i]        # newest of the trio (impulse completed)
            ts = window.index[i - 1]   # timestamp of the impulse (middle) candle

            if direction == "bullish" and c0["High"] < c2["Low"]:
                fvgs.append({
                    "direction": "bullish",
                    "bottom":    float(c0["High"]),
                    "top":       float(c2["Low"]),
                    "midpoint":  float((c0["High"] + c2["Low"]) / 2),
                    "timestamp": ts,
                })
            elif direction == "bearish" and c0["Low"] > c2["High"]:
                fvgs.append({
                    "direction": "bearish",
                    "bottom":    float(c2["High"]),
                    "top":       float(c0["Low"]),
                    "midpoint":  float((c0["Low"] + c2["High"]) / 2),
                    "timestamp": ts,
                })

        return fvgs

    # ── Setup detection (single pair) ─────────────────────────────────────────

    def _check_pair(self, pair: str) -> Optional[dict]:
        """
        Run the full strategy check for one forex pair.
        Returns a setup dict if all conditions are met, otherwise None.
        """
        # ── Fetch data ────────────────────────────────────────────────────────
        df_1h = self._get_1h_candles(pair)
        df_4h = self._resample_4h(df_1h)

        if len(df_4h) < MIN_CANDLES:
            logger.debug("%s: insufficient 4H candles (%d).", pair, len(df_4h))
            return None

        # ── Step 1: Determine 4H trend ────────────────────────────────────────
        df_4h["ema50"]  = self._ema(df_4h["Close"], 50)
        df_4h["ema200"] = self._ema(df_4h["Close"], 200)

        ema50_now  = df_4h["ema50"].iloc[-1]
        ema200_now = df_4h["ema200"].iloc[-1]
        trend      = "bullish" if ema50_now > ema200_now else "bearish"

        current_price = float(df_4h["Close"].iloc[-1])

        # ── Step 2: Find 4H FVGs aligned with the trend ───────────────────────
        fvgs = self._find_fvgs(df_4h, trend)
        if not fvgs:
            logger.debug("%s: no %s FVGs found.", pair, trend)
            return None

        # ── Step 3: Is price pulling back into a 4H FVG? ─────────────────────
        active_fvg = None
        for fvg in reversed(fvgs):  # most recent first
            if fvg["bottom"] <= current_price <= fvg["top"]:
                active_fvg = fvg
                break

        if active_fvg is None:
            logger.debug(
                "%s: price %.5f not inside any %s FVG.", pair, current_price, trend
            )
            return None

        # ── Step 4: 1H confirmation ───────────────────────────────────────────
        if not self._confirm_1h(df_1h, trend):
            logger.debug("%s: 1H confirmation failed for %s setup.", pair, trend)
            return None

        logger.info(
            "SETUP FOUND — %s %s | price %.5f | FVG [%.5f – %.5f]",
            pair, trend.upper(), current_price, active_fvg["bottom"], active_fvg["top"],
        )

        return {
            "pair":          pair,
            "trend":         trend,
            "direction":     trend,   # alias used by alert formatter
            "current_price": current_price,
            "ema50":         float(ema50_now),
            "ema200":        float(ema200_now),
            "fvg":           active_fvg,
            "fvg_ts":        active_fvg["timestamp"],
            "scanned_at":    datetime.now(timezone.utc),
        }

    # ── 1H confirmation ───────────────────────────────────────────────────────

    @staticmethod
    def _confirm_1h(df_1h: pd.DataFrame, direction: str) -> bool:
        """
        Simple 1H candle-structure confirmation.

        Bullish: ≥ 2 of the last 3 candles are bullish (close > open)
                 AND the final candle is bullish.
        Bearish: ≥ 2 of the last 3 candles are bearish (close < open)
                 AND the final candle is bearish.
        """
        recent = df_1h.tail(3)
        if len(recent) < 2:
            return False

        last = recent.iloc[-1]

        if direction == "bullish":
            bullish = sum(1 for _, c in recent.iterrows() if c["Close"] > c["Open"])
            return bullish >= 2 and last["Close"] > last["Open"]

        if direction == "bearish":
            bearish = sum(1 for _, c in recent.iterrows() if c["Close"] < c["Open"])
            return bearish >= 2 and last["Close"] < last["Open"]

        return False

    # ── Alert formatting ───────────────────────────────────────────────────────

    def _format_alert(self, setup: dict) -> str:
        pair      = setup["pair"]
        direction = setup["direction"]
        action    = "BUY" if direction == "bullish" else "SELL"
        dir_word  = "bullish" if direction == "bullish" else "bearish"

        return (
            f"{pair} — potential {action}. "
            f"Price is pulling back into a {dir_word} FVG on the 4 hour "
            f"with {dir_word} EMA structure."
        )

    def _format_scan_result(self, setups: list[dict]) -> str:
        """Build a spoken summary for an on-demand scan."""
        if not setups:
            return "No setups on any pair at this time, sir."

        lines = []
        for s in setups:
            action   = "BUY" if s["direction"] == "bullish" else "SELL"
            dir_word = s["direction"]
            lines.append(
                f"{s['pair']}: potential {action}, "
                f"price pulling back into a {dir_word} FVG on the 4 hour"
            )

        return "  ".join(lines) + "."

    # ── Cooldown / dedup ──────────────────────────────────────────────────────

    def _is_on_cooldown(self, pair: str, direction: str) -> bool:
        key = (pair, direction)
        last = self._last_alerted.get(key)
        if last is None:
            return False
        return datetime.now(timezone.utc) - last < timedelta(hours=ALERT_COOLDOWN_HOURS)

    def _mark_alerted(self, pair: str, direction: str):
        self._last_alerted[(pair, direction)] = datetime.now(timezone.utc)

    # ── Scan execution ────────────────────────────────────────────────────────

    def _run_scan(self) -> list[dict]:
        """Scan all pairs; push background alerts for new setups."""
        if self._data_source == "none":
            return []

        setups = []
        for pair in PAIRS:
            try:
                setup = self._check_pair(pair)
                if setup is None:
                    continue

                setups.append(setup)

                # Only announce if not recently alerted for this pair + direction
                if not self._is_on_cooldown(pair, setup["direction"]):
                    self._mark_alerted(pair, setup["direction"])
                    msg = self._format_alert(setup)
                    self.notification_queue.put(msg)
                    logger.info("Alert queued for %s %s.", pair, setup["direction"])

            except Exception as exc:
                logger.warning("Error scanning %s: %s", pair, exc)

        return setups

    def scan_now(self) -> str:
        """
        On-demand scan triggered by voice command.
        Runs synchronously and returns a spoken result string.
        """
        logger.info("On-demand market scan triggered.")
        try:
            setups = self._run_scan()
            return self._format_scan_result(setups)
        except Exception as exc:
            logger.error("On-demand scan error: %s", exc, exc_info=True)
            return "I ran into an error during the market scan, sir.  Please try again."

    # ── Background thread ─────────────────────────────────────────────────────

    def _scanner_loop(self):
        """Daemon thread: wait a moment for JARVIS to finish starting up,
        then scan on a fixed interval."""
        time.sleep(30)  # let JARVIS initialise before first scan
        while True:
            try:
                self._run_scan()
            except Exception as exc:
                logger.error("Background scan error: %s", exc)
            time.sleep(SCAN_INTERVAL_MINUTES * 60)

    def _start_scanner(self):
        t = threading.Thread(
            target=self._scanner_loop,
            daemon=True,
            name="MarketScannerThread",
        )
        t.start()
