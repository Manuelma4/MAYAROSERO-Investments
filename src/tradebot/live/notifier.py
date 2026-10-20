"""Alert channels: console, email (SMTP) and WhatsApp (Twilio).

Credentials always come from environment variables, never from the config
file, so they are not committed to git. See `.env.example`.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)


class ConsoleNotifier:
    def send(self, text: str) -> None:
        print(text, flush=True)


class EmailNotifier:
    """Sends alerts by email over SMTP (STARTTLS).

    Env vars: SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD,
    ALERT_EMAIL_TO (comma separated), ALERT_EMAIL_FROM (default SMTP_USER).
    For Gmail use smtp.gmail.com and an App Password (not your normal one).
    """

    def __init__(self):
        env = os.environ.get
        self.host, self.port = env("SMTP_HOST"), int(env("SMTP_PORT", "587"))
        self.user, self.password = env("SMTP_USER"), env("SMTP_PASSWORD")
        self.to = [a.strip() for a in env("ALERT_EMAIL_TO", "").split(",") if a.strip()]
        self.sender = env("ALERT_EMAIL_FROM") or self.user
        if not (self.host and self.user and self.password and self.to):
            raise ValueError("SMTP_HOST, SMTP_USER, SMTP_PASSWORD and ALERT_EMAIL_TO must be set")

    def deliver(self, text: str) -> None:
        """Send and raise on failure (used by scripts/test_alerts.py)."""
        msg = EmailMessage()
        msg["Subject"] = "MAYAROSERO: " + text.splitlines()[0][:120]
        msg["From"], msg["To"] = self.sender, ", ".join(self.to)
        msg.set_content(text)
        with smtplib.SMTP(self.host, self.port, timeout=15) as s:
            s.starttls()
            s.login(self.user, self.password)
            s.send_message(msg)

    def send(self, text: str) -> None:
        try:
            self.deliver(text)
        except Exception as exc:  # never let an alert failure kill the bot
            log.warning("Email send failed: %s", exc)


class WhatsAppNotifier:
    """Sends alerts to WhatsApp through the Twilio API.

    Env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM
    (e.g. whatsapp:+14155238886 for the Twilio sandbox) and WHATSAPP_TO
    (your number, e.g. whatsapp:+33612345678). To use the free sandbox, send
    the join code shown in the Twilio console from your phone first.
    """

    def __init__(self):
        env = os.environ.get
        self.sid, self.token = env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN")
        self.sender, self.to = env("TWILIO_WHATSAPP_FROM"), env("WHATSAPP_TO")
        if not (self.sid and self.token and self.sender and self.to):
            raise ValueError("TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM "
                             "and WHATSAPP_TO must be set")
        self.sender = self.sender if self.sender.startswith("whatsapp:") else f"whatsapp:{self.sender}"
        self.to = self.to if self.to.startswith("whatsapp:") else f"whatsapp:{self.to}"

    def deliver(self, text: str) -> None:
        """Send and raise on failure (used by scripts/test_alerts.py)."""
        import requests

        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
            data={"From": self.sender, "To": self.to, "Body": text[:1500]},
            auth=(self.sid, self.token), timeout=15)
        if r.status_code >= 300:
            raise RuntimeError(f"Twilio answered {r.status_code}: {r.text[:200]}")

    def send(self, text: str) -> None:
        try:
            self.deliver(text)
        except Exception as exc:
            log.warning("WhatsApp send failed: %s", exc)


CHANNELS = {"console": ConsoleNotifier, "email": EmailNotifier, "whatsapp": WhatsAppNotifier}


def build_notifiers(names: list[str]) -> list:
    out = []
    for n in names:
        if n not in CHANNELS:
            log.warning("Unknown notifier '%s' (available: %s)", n, ", ".join(CHANNELS))
            continue
        try:
            out.append(CHANNELS[n]())
        except ValueError as exc:
            log.warning("%s alerts disabled: %s", n, exc)
    return out or [ConsoleNotifier()]
