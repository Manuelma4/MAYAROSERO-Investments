"""Send one test message on every alert channel, and say plainly what is missing.

    python scripts/test_alerts.py               # email + whatsapp
    python scripts/test_alerts.py email         # just one channel
    docker compose exec app python scripts/test_alerts.py

Reads the same variables as the app (SMTP_*, ALERT_EMAIL_TO, TWILIO_*, WHATSAPP_TO).
Load a local .env first with:  set -a; . ./.env; set +a
"""

from __future__ import annotations

import sys
from datetime import datetime

from tradebot.live.notifier import CHANNELS

TEXT = (f"[TEST] MAYAROSERO Investments alert check, {datetime.now():%d %b %H:%M}.\n"
        "If you can read this, this channel works. Real alerts look like:\n"
        "[PRICE ALERT] AAPL is above 250 (now 251.30, +2.1% today)")


def main(names: list[str]) -> int:
    failed = 0
    for name in names or ["email", "whatsapp"]:
        cls = CHANNELS.get(name)
        if cls is None:
            print(f"{name}: unknown channel (use: {', '.join(c for c in CHANNELS if c != 'console')})")
            failed += 1
            continue
        try:
            cls().deliver(TEXT)
            print(f"{name}: sent. Check your {'inbox (and spam folder)' if name == 'email' else 'WhatsApp'}.")
        except Exception as exc:  # show the real reason: missing variable, wrong password, ...
            print(f"{name}: NOT sent: {exc}")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
