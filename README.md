# JARVIS — Just A Rather Very Intelligent System

A production-quality AI voice assistant for Windows 11, modelled on the iconic AI from Iron Man.

```
Say "Hey Jarvis" → JARVIS wakes up → you speak your command → Claude AI responds → ElevenLabs British voice answers
```

---

## Features

| Category | Capabilities |
|---|---|
| **Voice** | Wake word detection · OpenAI Whisper STT · ElevenLabs British voice · Sci-fi activation chime |
| **AI** | Natural multi-turn conversation via Claude · Answers any question · Tells jokes |
| **Web** | Google/DuckDuckGo search + AI summary · Live news headlines (BBC RSS or NewsAPI) |
| **Data** | Live weather for Newcastle, AU · Live GBP/USD and EUR/USD forex rates |
| **Productivity** | Read & summarise emails (IMAP/Gmail) · Timers · Alarms · Time & date |
| **System** | Open any app or website · System volume control · Safe calculator |
| **Memory** | Remembers facts across sessions (persisted to `data/memory.json`) |

---

## Requirements

- Windows 10 / 11
- Python 3.11 or 3.12
- A working microphone
- Internet connection (for API calls)

---

## Installation

### 1 — Clone / download

```bat
git clone https://github.com/your-username/jarvis.git
cd jarvis
```

### 2 — Create a virtual environment (strongly recommended)

```bat
python -m venv .venv
.venv\Scripts\activate
```

### 3 — Install dependencies

```bat
pip install -r requirements.txt
```

> **PyAudio troubleshooting** — if `pip install pyaudio` fails on Windows:
> ```bat
> pip install pipwin
> pipwin install pyaudio
> ```
> Or download the pre-built wheel from
> https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio and install with
> `pip install pyaudio‑0.2.14‑cp312‑cp312‑win_amd64.whl`.

### 4 — Configure your API keys

```bat
copy .env.example .env
notepad .env
```

Fill in your keys (see the **API Keys** section below).

### 5 — Run JARVIS

```bat
python main.py
```

Say **"Hey Jarvis"** to activate.

---

## API Keys

### Required

| Key | Where to get it | Free tier? |
|---|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/ | Pay-per-use, ~$0.003/1k tokens |
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys | Pay-per-use, ~$0.006/min audio |
| `ELEVENLABS_API_KEY` | https://elevenlabs.io/ | ✅ 10 000 chars/month free |

### Optional (JARVIS works without these, with fallbacks)

| Key | Purpose | Fallback |
|---|---|---|
| `OPENWEATHER_API_KEY` | Weather data | wttr.in (free, no key) |
| `NEWS_API_KEY` | News headlines | BBC RSS feed (free) |
| `ALPHA_VANTAGE_API_KEY` | Forex rates | Open Exchange Rates (free) |
| `EMAIL_ADDRESS` + `EMAIL_PASSWORD` | Email reading | Disabled gracefully |

---

## Voice Commands Reference

### General

| Say | JARVIS does |
|---|---|
| "Hey Jarvis" | Wakes up and plays activation chime |
| "Hey Jarvis, what time is it?" | Tells the current time |
| "Hey Jarvis, what's today's date?" | Tells today's date and day |
| "Hey Jarvis, tell me a joke" | Tells a dry British joke |
| "Hey Jarvis, stop / that's all" | Dismisses and goes back to listening |

### Weather

| Say | Example |
|---|---|
| "What's the weather?" | "Currently in Newcastle, AU: Partly cloudy, 22°C…" |
| "What's the temperature?" | Same |
| "Will it rain today?" | Same |

### Web & News

| Say | Example |
|---|---|
| "Search for the history of the Eiffel Tower" | AI-summarised web results |
| "Google for best Python tutorials" | Same |
| "What's in the news?" | Top 6 headlines from BBC / NewsAPI |
| "Give me today's headlines" | Same |

### Apps & Websites

| Say | Example |
|---|---|
| "Open Spotify" | Launches Spotify |
| "Open Chrome" | Launches Google Chrome |
| "Open YouTube" | Opens youtube.com in your browser |
| "Go to bbc.co.uk" | Opens that URL |
| "Launch VS Code" | Launches Visual Studio Code |

### Finance

| Say | Example |
|---|---|
| "What's the forex rate?" | "GBP/USD is 1.2734, EUR/USD is 1.0812" |
| "Check the pound dollar rate" | Same |
| "What's GBPUSD?" | Same |

### Timers & Alarms

| Say | Example |
|---|---|
| "Set a 5 minute timer" | Timer fires after 5 minutes |
| "Timer for 30 seconds" | Timer fires after 30 seconds |
| "Set an alarm for 7am" | Alarm at 07:00 |
| "Wake me at 6:30" | Alarm at 06:30 |

### Email

| Say | Example |
|---|---|
| "Read my emails" | AI-summarised inbox briefing |
| "Check my inbox" | Same |
| "Any messages?" | Same |

### Memory

| Say | Example |
|---|---|
| "Remember that my wife's name is Sarah" | Stored persistently |
| "Note that my car reg is AB12 CDE" | Stored persistently |
| "What do you remember?" | JARVIS reads back all stored notes |
| "Remind me of my notes" | Same |

### Volume & System

| Say | Example |
|---|---|
| "Set volume to 60 percent" | Sets Windows volume to 60% |
| "Turn up the volume" | Increases by 15% |
| "Turn down the volume" | Decreases by 15% |
| "Mute" | Mutes system audio |
| "Unmute" | Unmutes system audio |

### Calculator

| Say | Example |
|---|---|
| "Calculate 15 percent of 340" | "The answer is 51, sir." |
| "What is 1234 times 56?" | "The answer is 69,104, sir." |
| "What's 2 to the power of 10?" | "The answer is 1,024, sir." |

---

## Configuration

All settings live in `.env`.  Key options:

```env
# Change Claude model (cheaper ← → smarter)
CLAUDE_MODEL=claude-haiku-4-5-20251001    # fastest, cheapest
CLAUDE_MODEL=claude-sonnet-4-6            # default: balanced
CLAUDE_MODEL=claude-opus-4-6              # most powerful

# Change ElevenLabs voice
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb  # George (warm British male)

# Change weather location
WEATHER_CITY=Sydney
WEATHER_COUNTRY=AU
```

---

## Offline / No-OpenAI Mode

JARVIS can run Whisper **locally** without an OpenAI API key:

1. Install extra dependencies:
   ```bat
   pip install openai-whisper torch
   ```
   *(Requires ~1.5 GB disk space and FFmpeg — see https://ffmpeg.org/download.html)*

2. In `.env`, leave `OPENAI_API_KEY` blank.  JARVIS will auto-detect and use
   the local `base` model (or whatever `WHISPER_LOCAL_MODEL` is set to).

---

## Project Structure

```
jarvis/
├── main.py                  ← Entry point — run this
├── jarvis.py                ← Core orchestrator
├── modules/
│   ├── voice_input.py       ← Wake word + Whisper STT
│   ├── voice_output.py      ← ElevenLabs TTS + activation sound
│   ├── ai_brain.py          ← Claude API + conversation history
│   ├── app_control.py       ← Open apps and websites
│   ├── web_search.py        ← DuckDuckGo search
│   ├── weather.py           ← OpenWeatherMap / wttr.in
│   ├── timer_alarm.py       ← Countdown timers and alarms
│   ├── email_reader.py      ← IMAP email reader
│   ├── forex.py             ← Live forex rates
│   ├── memory.py            ← Persistent cross-session memory
│   ├── news.py              ← NewsAPI / BBC RSS
│   └── system_control.py    ← Volume, time/date, calculator
├── data/
│   └── memory.json          ← Persistent memory store (auto-managed)
├── sounds/
│   └── activation.wav       ← Generated on first run
├── logs/
│   └── jarvis.log           ← Rolling log file
├── .env                     ← Your API keys (never commit this)
├── .env.example             ← Template
└── requirements.txt
```

---

## Troubleshooting

**JARVIS doesn't hear me**
- Check your default microphone in Windows Sound Settings.
- Run with the room quiet for the first 2 seconds (microphone calibration).
- Try moving closer to the microphone or increasing mic boost in Windows.

**"Hey Jarvis" not recognised**
- Speak clearly and at a normal pace.
- The wake word detection uses Google STT — ensure you have internet access.
- Try alternatives: "Jarvis", "Hey J.A.R.V.I.S."

**Voice sounds robotic / no ElevenLabs**
- Verify `ELEVENLABS_API_KEY` is correct in `.env`.
- Check your ElevenLabs character quota at https://elevenlabs.io/

**PyAudio / microphone errors**
- See the PyAudio installation note in the Installation section above.
- Ensure no other app has exclusive microphone access.

**Email not working (Gmail)**
- Use an **App Password**, not your Gmail password.
- Enable 2FA, then generate an app password at https://myaccount.google.com/apppasswords
- Make sure IMAP is enabled in Gmail Settings → See all settings → Forwarding and POP/IMAP.

**Forex rates returning zeros**
- Alpha Vantage free tier allows 25 requests/day.  If exhausted, the fallback
  Open Exchange Rates API is used automatically.

---

## Privacy & Security

- All API keys are stored locally in `.env` — never committed to git (`.gitignore` covers it).
- Voice audio is sent to OpenAI Whisper API only after the wake word is detected.
- Conversation history is held in memory only (not saved to disk).
- Memories you explicitly store are saved locally in `data/memory.json`.

---

## Licence

MIT — free to use, modify, and distribute.
