"""
app_control.py — Open applications and websites on Windows.

Handles commands like:
  "Open Spotify"
  "Launch Chrome"
  "Open Google"
  "Go to youtube.com"
"""

import logging
import os
import re
import subprocess
import webbrowser
from urllib.parse import quote_plus

logger = logging.getLogger("JARVIS.AppControl")

# Map of common spoken names → Windows executable names
# JARVIS will also try the name directly if it's not in this dict.
KNOWN_APPS: dict[str, str] = {
    # Browsers
    "chrome":          "chrome.exe",
    "google chrome":   "chrome.exe",
    "firefox":         "firefox.exe",
    "mozilla firefox": "firefox.exe",
    "edge":            "msedge.exe",
    "microsoft edge":  "msedge.exe",
    "brave":           "brave.exe",
    "opera":           "opera.exe",

    # Microsoft Office
    "word":            "WINWORD.EXE",
    "microsoft word":  "WINWORD.EXE",
    "excel":           "EXCEL.EXE",
    "microsoft excel": "EXCEL.EXE",
    "powerpoint":      "POWERPNT.EXE",
    "outlook":         "OUTLOOK.EXE",
    "teams":           "Teams.exe",
    "microsoft teams": "Teams.exe",
    "onenote":         "ONENOTE.EXE",

    # Media
    "spotify":         "Spotify.exe",
    "vlc":             "vlc.exe",
    "media player":    "wmplayer.exe",
    "windows media player": "wmplayer.exe",

    # Dev tools
    "vs code":         "Code.exe",
    "vscode":          "Code.exe",
    "visual studio code": "Code.exe",
    "visual studio":   "devenv.exe",
    "pycharm":         "pycharm64.exe",
    "notepad":         "notepad.exe",
    "notepad++":       "notepad++.exe",
    "git bash":        "git-bash.exe",
    "terminal":        "wt.exe",
    "windows terminal": "wt.exe",
    "powershell":      "powershell.exe",
    "command prompt":  "cmd.exe",
    "cmd":             "cmd.exe",

    # System
    "file explorer":   "explorer.exe",
    "explorer":        "explorer.exe",
    "task manager":    "taskmgr.exe",
    "control panel":   "control.exe",
    "settings":        "ms-settings:",
    "calculator":      "calc.exe",
    "paint":           "mspaint.exe",
    "snipping tool":   "SnippingTool.exe",
    "camera":          "microsoft.windows.camera:",

    # Communication
    "discord":         "Discord.exe",
    "slack":           "slack.exe",
    "zoom":            "Zoom.exe",
    "skype":           "Skype.exe",
    "whatsapp":        "WhatsApp.exe",

    # Gaming
    "steam":           "steam.exe",
    "epic games":      "EpicGamesLauncher.exe",

    # Other
    "obs":             "obs64.exe",
    "obs studio":      "obs64.exe",
    "photoshop":       "Photoshop.exe",
}

# Spoken website names → URLs.
# Checked BEFORE any exe attempt, so these always open in the browser.
KNOWN_SITES: dict[str, str] = {
    # Search & Google services
    "google":            "https://www.google.com",
    "gmail":             "https://mail.google.com",
    "google mail":       "https://mail.google.com",
    "google drive":      "https://drive.google.com",
    "google docs":       "https://docs.google.com",
    "google sheets":     "https://sheets.google.com",
    "google maps":       "https://maps.google.com",
    "google calendar":   "https://calendar.google.com",
    "google meet":       "https://meet.google.com",
    "youtube":           "https://www.youtube.com",

    # Social & news
    "facebook":          "https://www.facebook.com",
    "twitter":           "https://www.twitter.com",
    "x":                 "https://www.x.com",
    "instagram":         "https://www.instagram.com",
    "reddit":            "https://www.reddit.com",
    "linkedin":          "https://www.linkedin.com",
    "tiktok":            "https://www.tiktok.com",
    "pinterest":         "https://www.pinterest.com",
    "snapchat":          "https://www.snapchat.com",

    # News
    "bbc":               "https://www.bbc.co.uk",
    "bbc news":          "https://www.bbc.co.uk/news",
    "sky news":          "https://news.sky.com",
    "the guardian":      "https://www.theguardian.com",
    "guardian":          "https://www.theguardian.com",
    "cnn":               "https://www.cnn.com",
    "reuters":           "https://www.reuters.com",

    # Finance & trading
    "tradingview":       "https://www.tradingview.com",
    "trading view":      "https://www.tradingview.com",
    "binance":           "https://www.binance.com",
    "coinbase":          "https://www.coinbase.com",
    "kraken":            "https://www.kraken.com",
    "investing":         "https://www.investing.com",
    "investing.com":     "https://www.investing.com",
    "yahoo finance":     "https://finance.yahoo.com",
    "market watch":      "https://www.marketwatch.com",
    "marketwatch":       "https://www.marketwatch.com",
    "bloomberg":         "https://www.bloomberg.com",
    "paypal":            "https://www.paypal.com",
    "wise":              "https://www.wise.com",

    # Shopping
    "amazon":            "https://www.amazon.co.uk",
    "ebay":              "https://www.ebay.co.uk",
    "etsy":              "https://www.etsy.com",

    # Entertainment
    "netflix":           "https://www.netflix.com",
    "disney plus":       "https://www.disneyplus.com",
    "disney+":           "https://www.disneyplus.com",
    "prime video":       "https://www.primevideo.com",
    "spotify":           "https://open.spotify.com",
    "twitch":            "https://www.twitch.tv",

    # Dev & productivity
    "github":            "https://www.github.com",
    "gitlab":            "https://www.gitlab.com",
    "stackoverflow":     "https://stackoverflow.com",
    "stack overflow":    "https://stackoverflow.com",
    "wikipedia":         "https://www.wikipedia.org",
    "notion":            "https://www.notion.so",
    "trello":            "https://www.trello.com",
    "jira":              "https://www.atlassian.com/software/jira",
    "figma":             "https://www.figma.com",
    "canva":             "https://www.canva.com",

    # AI tools
    "chatgpt":           "https://chat.openai.com",
    "claude":            "https://claude.ai",
    "perplexity":        "https://www.perplexity.ai",
    "midjourney":        "https://www.midjourney.com",

    # Weather
    "weather":           "https://www.bom.gov.au/nsw/forecasts/newcastle.shtml",
    "bom":               "https://www.bom.gov.au",
}


class AppControl:
    """Opens desktop applications and websites for the user."""

    def open_target(self, target: str) -> str:
        """
        Decide whether to open an app or website and do it.
        Returns a spoken confirmation.
        """
        target_clean = target.lower().strip(" .,")

        # 1. Check known websites first
        if target_clean in KNOWN_SITES:
            url = KNOWN_SITES[target_clean]
            return self._open_url(url, target_clean)

        # 2. Check if target looks like a URL / domain
        if self._looks_like_url(target_clean):
            url = target_clean if target_clean.startswith("http") else f"https://{target_clean}"
            return self._open_url(url, target_clean)

        # 3. Check known app list
        if target_clean in KNOWN_APPS:
            return self._launch_app(KNOWN_APPS[target_clean], target_clean)

        # 4. Guess a website URL for single/compound words that look like web
        #    services (e.g. "tradingview" → https://www.tradingview.com).
        #    Only do this when the target has no spaces or is hyphenated and
        #    does NOT match a known desktop-app name — prevents "open notepad"
        #    from routing to notepad.com instead of notepad.exe.
        slug = target_clean.replace(" ", "").replace("-", "")
        if slug.isalpha() and target_clean not in KNOWN_APPS:
            guessed_url = f"https://www.{slug}.com"
            logger.info("Guessing website URL: %s", guessed_url)
            return self._open_url(guessed_url, target_clean)

        # 5. Try launching by name directly (user may have an unlisted desktop app)
        exe = target_clean.replace(" ", "") + ".exe"
        result = self._launch_app(exe, target_clean)
        if "Unable" not in result:
            return result

        # 6. Fall back to opening a Google search for the target
        logger.info("App '%s' not found — opening Google search.", target_clean)
        search_url = f"https://www.google.com/search?q={quote_plus(target)}"
        webbrowser.open(search_url)
        return (
            f"I couldn't find a local application called {target}, sir, "
            "so I've opened a Google search for it instead."
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _looks_like_url(self, text: str) -> bool:
        return bool(
            re.match(r"(https?://|www\.)[\w\-./]+", text)
            or re.match(r"[\w\-]+\.(com|co\.uk|org|net|io|gov|edu|au|co|app)", text)
        )

    def _open_url(self, url: str, name: str) -> str:
        try:
            webbrowser.open(url)
            logger.info("Opened URL: %s", url)
            return f"Opening {name} for you now, sir."
        except Exception as exc:
            logger.error("Failed to open URL '%s': %s", url, exc)
            return f"I had trouble opening {name}, sir. Please check it manually."

    def _launch_app(self, exe: str, friendly_name: str) -> str:
        """Attempt to launch an executable by name (relies on PATH or ms-settings:)."""
        try:
            # Handle ms-settings: URI scheme (e.g. "ms-settings:")
            if exe.startswith("ms-") or exe.endswith(":"):
                os.startfile(exe)
            else:
                subprocess.Popen(
                    exe,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            logger.info("Launched: %s", exe)
            return f"Opening {friendly_name} now, sir."
        except FileNotFoundError:
            logger.warning("Executable not found: %s", exe)
            return f"Unable to find {friendly_name} on your system, sir."
        except Exception as exc:
            logger.error("Failed to launch '%s': %s", exe, exc)
            return f"I wasn't able to launch {friendly_name}, sir."
