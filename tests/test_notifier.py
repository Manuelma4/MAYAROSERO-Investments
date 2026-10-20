import smtplib

import pytest

from tradebot.live.notifier import EmailNotifier, WhatsAppNotifier

EMAIL_ENV = {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "me@example.com", "SMTP_PASSWORD": "pw",
             "ALERT_EMAIL_TO": "me@example.com"}
WA_ENV = {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t", "TWILIO_WHATSAPP_FROM": "whatsapp:+1",
          "WHATSAPP_TO": "whatsapp:+33"}


def test_email_deliver_raises_but_send_never_does(monkeypatch):
    for k, v in EMAIL_ENV.items():
        monkeypatch.setenv(k, v)

    class BadLogin:
        def __init__(self, *a, **kw): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): ...
        def login(self, *a): raise smtplib.SMTPAuthenticationError(535, b"bad password")

    monkeypatch.setattr(smtplib, "SMTP", BadLogin)
    n = EmailNotifier()
    with pytest.raises(smtplib.SMTPAuthenticationError):
        n.deliver("[TEST] hello")
    n.send("[TEST] hello")   # the app keeps running when an alert cannot be delivered


def test_whatsapp_deliver_reports_twilio_errors(monkeypatch):
    import requests

    for k, v in WA_ENV.items():
        monkeypatch.setenv(k, v)

    class Resp:
        status_code, text = 401, "Authenticate"

    monkeypatch.setattr(requests, "post", lambda *a, **kw: Resp())
    with pytest.raises(RuntimeError, match="401"):
        WhatsAppNotifier().deliver("[TEST] hello")
    WhatsAppNotifier().send("[TEST] hello")


def test_missing_settings_are_named(monkeypatch):
    for k in EMAIL_ENV:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValueError, match="SMTP_HOST"):
        EmailNotifier()
