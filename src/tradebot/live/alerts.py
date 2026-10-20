"""Custom price alerts: "tell me when AAPL goes above 250", "... below 200", "... moves 5% in a day".

`due(alert, quote)` is a pure check so it is easy to test; the precomputer calls it every few
minutes with fresh quotes and fires notifiers + the in-app bell for each alert that is due.
An alert fires once, then deactivates (the user can re-arm it).
"""

from __future__ import annotations

KINDS = {
    "above": "Price rises to or above",
    "below": "Price falls to or below",
    "move": "Moves at least this % in one day (up or down)",
}


def due(alert: dict, quote: dict) -> bool:
    price = quote.get("price")
    if price is None or not alert.get("active", True):
        return False
    kind, value = alert["kind"], float(alert["value"])
    if kind == "above":
        return price >= value
    if kind == "below":
        return price <= value
    if kind == "move":   # after a re-arm, only a new day's move counts (not the same stale daily bar)
        if alert.get("last_bar") and str(quote.get("time") or "") <= str(alert["last_bar"]):
            return False
        return abs(quote.get("change_pct") or 0.0) >= value
    return False


def message(alert: dict, quote: dict) -> str:
    sym, price, chg = alert["symbol"], quote["price"], quote.get("change_pct") or 0.0
    if alert["kind"] == "move":
        what = f"moved {chg:+.1f}% today (your alert: {float(alert['value']):g}%)"
    else:
        word = "above" if alert["kind"] == "above" else "below"
        what = f"is {word} {float(alert['value']):g} (now {price:.2f}, {chg:+.1f}% today)"
    note = f"\n  {alert['note']}" if alert.get("note") else ""
    return f"[PRICE ALERT] {sym} {what}{note}"
