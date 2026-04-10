"""
email_reader.py — Read emails via IMAP.

Connects to any IMAP server (defaults to Gmail).
Returns a list of email dicts that ai_brain then summarises.

Required .env keys (all optional — gracefully disabled if absent):
  EMAIL_ADDRESS   — your email address
  EMAIL_PASSWORD  — app password (Gmail: https://myaccount.google.com/apppasswords)
  EMAIL_IMAP_SERVER — default: imap.gmail.com
  EMAIL_IMAP_PORT   — default: 993
"""

import email
import imaplib
import logging
import os
import re
from email.header import decode_header

logger = logging.getLogger("JARVIS.EmailReader")

DEFAULT_IMAP_SERVER = "imap.gmail.com"
DEFAULT_IMAP_PORT   = 993


class EmailReader:
    """Reads recent/unread emails from an IMAP inbox."""

    def __init__(self):
        self._address  = os.getenv("EMAIL_ADDRESS")
        self._password = os.getenv("EMAIL_PASSWORD")
        self._server   = os.getenv("EMAIL_IMAP_SERVER", DEFAULT_IMAP_SERVER)
        self._port     = int(os.getenv("EMAIL_IMAP_PORT", DEFAULT_IMAP_PORT))

        if self._address and self._password:
            logger.info("Email reader configured (%s).", self._address)
        else:
            logger.info("Email credentials not configured — email features disabled.")

    # ── Public interface ──────────────────────────────────────────────────────

    def get_recent_emails(self, max_emails: int = 5) -> list[dict]:
        """
        Fetch the most recent unread emails.
        Returns a list of dicts: {sender, subject, snippet, date}.
        Returns an empty list (or error info) if unconfigured or on failure.
        """
        if not self._address or not self._password:
            return [{"error": "Email is not configured.  Please add EMAIL_ADDRESS and EMAIL_PASSWORD to your .env file."}]

        try:
            return self._fetch(max_emails)
        except imaplib.IMAP4.error as exc:
            logger.error("IMAP auth/protocol error: %s", exc)
            return [{"error": "I couldn't log into your email account, sir.  Please check the credentials in your .env file."}]
        except ConnectionRefusedError:
            return [{"error": f"Cannot connect to {self._server}.  Check your IMAP server settings."}]
        except Exception as exc:
            logger.error("Email fetch error: %s", exc, exc_info=True)
            return [{"error": "An unexpected error occurred while reading your email, sir."}]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _fetch(self, max_emails: int) -> list[dict]:
        results = []

        with imaplib.IMAP4_SSL(self._server, self._port) as mail:
            mail.login(self._address, self._password)
            mail.select("INBOX")

            # Search for unseen messages; fall back to ALL if inbox is empty
            _, ids_unseen = mail.search(None, "UNSEEN")
            ids = ids_unseen[0].split()

            if not ids:
                _, ids_all = mail.search(None, "ALL")
                ids = ids_all[0].split()

            if not ids:
                return []

            # Fetch the most recent max_emails messages
            for uid in reversed(ids[-max_emails:]):
                _, data = mail.fetch(uid, "(RFC822)")
                raw = data[0][1]
                msg = email.message_from_bytes(raw)

                results.append({
                    "sender":  self._decode_header(msg.get("From", "Unknown")),
                    "subject": self._decode_header(msg.get("Subject", "(no subject)")),
                    "date":    msg.get("Date", ""),
                    "snippet": self._extract_snippet(msg),
                })

        logger.info("Fetched %d emails.", len(results))
        return results

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _decode_header(raw: str) -> str:
        """Decode RFC 2047 encoded headers."""
        parts = decode_header(raw)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                try:
                    decoded.append(part.decode(charset or "utf-8", errors="replace"))
                except LookupError:
                    decoded.append(part.decode("utf-8", errors="replace"))
            else:
                decoded.append(str(part))
        return " ".join(decoded).strip()

    @staticmethod
    def _extract_snippet(msg: email.message.Message, max_chars: int = 200) -> str:
        """Extract a short plaintext snippet from the email body."""
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        charset = part.get_content_charset() or "utf-8"
                        body    = part.get_payload(decode=True).decode(charset, errors="replace")
                        break
                    except Exception:
                        continue
        else:
            try:
                charset = msg.get_content_charset() or "utf-8"
                body    = msg.get_payload(decode=True).decode(charset, errors="replace")
            except Exception:
                body = ""

        # Strip whitespace, quoted text, and HTML tags
        body = re.sub(r"<[^>]+>", " ", body)           # remove HTML
        body = re.sub(r"^>.*$", "", body, flags=re.M)  # remove quoted lines
        body = " ".join(body.split())                   # collapse whitespace
        return body[:max_chars]
