"""
ai_brain.py — Claude AI integration.

Responsibilities
────────────────
• Maintain multi-turn conversation history for natural back-and-forth chat.
• Provide helper methods that let other modules delegate formatting to Claude
  (search summaries, email summaries, news presentation, etc.).
• Tell jokes with British flavour.
• Persist and present the user's stored memories.
"""

import logging
import os

import anthropic

logger = logging.getLogger("JARVIS.AIBrain")

# Claude model to use — change to "claude-haiku-4-5-20251001" for faster/cheaper responses
DEFAULT_MODEL = "claude-sonnet-4-6"

# System prompt that defines JARVIS's personality
SYSTEM_PROMPT = """\
You are JARVIS (Just A Rather Very Intelligent System), a sophisticated AI \
personal assistant created to serve your user with brilliance and discretion.

Personality & style:
- Refined, intelligent, and occasionally witty with dry British humour.
- Concise and direct — your responses are spoken aloud, so never use bullet \
  points, markdown, or lengthy lists. Use natural, flowing sentences.
- Address the user as "sir" once per response at most (don't overdo it).
- Be warm but efficient. Get to the point quickly.

Voice-output constraints:
- Keep responses under four sentences unless the user explicitly asks for detail.
- Never recite URLs, file paths, or raw JSON.
- Avoid filler phrases like "Certainly!" or "Of course, I'd be happy to help!".
- Speak as if delivering polished briefings, not reading a wiki article.

Knowledge:
- Today's date is injected at runtime via the conversation.
- You have real-time access to weather, forex, news, and web data via specialised \
  modules; the results will be given to you to narrate naturally.
"""


class AIBrain:
    """Wraps the Anthropic Claude API for JARVIS."""

    # Keep at most this many message pairs in history to avoid token bloat
    MAX_HISTORY_PAIRS = 20

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = os.getenv("CLAUDE_MODEL", DEFAULT_MODEL)
        self._history: list[dict] = []
        logger.info("Claude AI ready (model: %s).", self._model)

    # ── History management ────────────────────────────────────────────────────

    def add_user_message(self, text: str):
        self._history.append({"role": "user", "content": text})
        self._trim_history()

    def add_assistant_message(self, text: str):
        self._history.append({"role": "assistant", "content": text})
        self._trim_history()

    def _trim_history(self):
        """Keep the conversation to the most recent MAX_HISTORY_PAIRS pairs."""
        max_msgs = self.MAX_HISTORY_PAIRS * 2
        if len(self._history) > max_msgs:
            self._history = self._history[-max_msgs:]

    def _ask(self, messages: list[dict], max_tokens: int = 512) -> str:
        """
        Core wrapper around the Anthropic API.
        Returns the text response or a graceful error string.
        """
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            return response.content[0].text.strip()
        except anthropic.RateLimitError:
            logger.warning("Claude API rate limit hit.")
            return "I'm being rate-limited at the moment, sir. Please try again shortly."
        except anthropic.APIConnectionError:
            logger.error("Cannot reach Claude API.")
            return "I can't reach my intelligence servers right now, sir. Please check your internet connection."
        except Exception as exc:
            logger.error("Claude API error: %s", exc)
            return "I'm afraid my cognitive functions are temporarily unavailable, sir."

    # ── General conversation ──────────────────────────────────────────────────

    def chat(self, user_input: str) -> str:
        """
        Handle free-form conversation using the full message history.
        This is the catch-all for anything not routed to a specialised module.
        """
        # Use the maintained history (already has the user message added by jarvis.py)
        response = self._ask(self._history)
        return response

    # ── Joke ──────────────────────────────────────────────────────────────────

    def tell_joke(self) -> str:
        """Ask Claude for a clever, dry British-style joke."""
        messages = [
            {
                "role": "user",
                "content": (
                    "Tell me a single clever joke. "
                    "Keep it short, dry, and British in flavour. "
                    "Do not explain it afterwards."
                ),
            }
        ]
        return self._ask(messages, max_tokens=200)

    # ── Search summary ────────────────────────────────────────────────────────

    def summarise_search_results(self, query: str, results: list[dict]) -> str:
        """
        Given raw DuckDuckGo results, ask Claude to narrate a summary.

        Parameters
        ----------
        query   : the original search query
        results : list of dicts with 'title' and 'body' keys
        """
        if not results:
            return (
                f"I'm afraid I couldn't find anything useful for '{query}', sir. "
                "Perhaps try rephrasing?"
            )

        snippets = "\n".join(
            f"- {r.get('title', '')}: {r.get('body', '')[:200]}"
            for r in results[:5]
        )
        messages = [
            {
                "role": "user",
                "content": (
                    f"The user searched for: '{query}'\n\n"
                    f"Here are the top web results:\n{snippets}\n\n"
                    "Summarise the key facts in 2–3 sentences, spoken naturally. "
                    "Do not mention that you're summarising search results."
                ),
            }
        ]
        return self._ask(messages, max_tokens=300)

    # ── News ──────────────────────────────────────────────────────────────────

    def present_news(self, headlines: list[str]) -> str:
        """Read out the top news headlines in JARVIS style."""
        if not headlines:
            return "I wasn't able to retrieve any headlines at the moment, sir."

        headline_text = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines[:6]))
        messages = [
            {
                "role": "user",
                "content": (
                    f"Present these news headlines to me in a polished briefing. "
                    f"Mention each one briefly. Keep it under 60 words total.\n\n"
                    f"{headline_text}"
                ),
            }
        ]
        return self._ask(messages, max_tokens=300)

    # ── Email summary ─────────────────────────────────────────────────────────

    def summarise_emails(self, emails: list[dict]) -> str:
        """
        Given a list of email dicts (subject, sender, snippet), give a briefing.
        """
        if not emails:
            return "Your inbox appears to be clear, sir. No unread messages."

        email_text = "\n".join(
            f"From {e.get('sender', 'Unknown')}: {e.get('subject', 'No subject')} "
            f"— {e.get('snippet', '')[:120]}"
            for e in emails[:5]
        )
        messages = [
            {
                "role": "user",
                "content": (
                    "Summarise these emails for me as a voice briefing. "
                    "Mention each sender and the gist. Keep it under 80 words.\n\n"
                    f"{email_text}"
                ),
            }
        ]
        return self._ask(messages, max_tokens=350)

    # ── Memory presentation ───────────────────────────────────────────────────

    def present_memories(self, memories: dict) -> str:
        """Narrate the user's stored memories."""
        if not memories:
            return "I don't have anything stored in memory at the moment, sir."

        mem_text = "\n".join(f"- {k}: {v}" for k, v in memories.items())
        messages = [
            {
                "role": "user",
                "content": (
                    "Here are the things I asked you to remember:\n\n"
                    f"{mem_text}\n\n"
                    "Read these back to me naturally in one or two sentences."
                ),
            }
        ]
        return self._ask(messages, max_tokens=250)
