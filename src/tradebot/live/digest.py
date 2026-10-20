"""Weekly digest: one short plain-English message (Sunday ~18:00 Paris by default) with the week's picks changes,
the alerts that fired, the live track record, portfolio drift and the market mood.

Pure functions (schedule maths and text), tested offline. The Precomputer sends it once per week through the
configured notifiers; the "already sent" mark lives in SQLite, so a restart never repeats it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MAX_CHARS = 1200        # WhatsApp-friendly
GRACE = timedelta(hours=12)   # a server that was down at the slot still sends it within this window


@dataclass(frozen=True)
class Schedule:
    day: int = 6            # 0 = Monday ... 6 = Sunday
    hour: int = 18
    minute: int = 0
    timezone: str = "Europe/Paris"
    enabled: bool = True

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def describe(self) -> str:
        return f"{DAYS[self.day].title()} at {self.hour:02d}:{self.minute:02d} ({self.timezone})"


def _day(v) -> int:
    s = str(v).strip().lower()
    if s.isdigit():   # 0-6 (Monday = 0) or 7 = Sunday (cron style)
        n = int(s)
        return 6 if n == 7 else n
    for i, d in enumerate(DAYS):
        if d.startswith(s[:3]):
            return i
    raise ValueError(f"Unknown digest day {v!r}")


def schedule_from(config: dict | None, env: dict | None = None) -> Schedule:
    """config.yaml `digest:` section, overridden by DIGEST_DAY / DIGEST_HOUR / DIGEST_TIMEZONE / DIGEST_ENABLED."""
    env = os.environ if env is None else env
    c = (config or {}).get("digest") or {}
    day = env.get("DIGEST_DAY") or c.get("day", "sunday")
    hour = env.get("DIGEST_HOUR") or c.get("hour", 18)
    tz = env.get("DIGEST_TIMEZONE") or c.get("timezone", "Europe/Paris")
    enabled = env.get("DIGEST_ENABLED")
    enabled = c.get("enabled", True) if enabled in (None, "") else enabled.strip().lower() in {"1", "true", "yes", "on"}
    h, _, m = str(hour).partition(":")   # "18" or "18:30"
    sch = Schedule(_day(day), int(h), int(m or c.get("minute", 0)), str(tz), bool(enabled))
    if not (0 <= sch.hour <= 23 and 0 <= sch.minute <= 59):
        raise ValueError(f"Invalid digest time {hour!r}")
    sch.tz   # raises for an unknown time zone
    return sch


def _aware(now) -> datetime:
    t = pd.Timestamp(now)
    return (t.tz_localize("UTC") if t.tzinfo is None else t).to_pydatetime()


def last_slot(now, sch: Schedule) -> datetime:
    """The most recent scheduled moment at or before `now` (in the schedule's time zone, DST included)."""
    local = _aware(now).astimezone(sch.tz)
    d = local.date() - timedelta(days=(local.weekday() - sch.day) % 7)
    slot = datetime.combine(d, time(sch.hour, sch.minute), tzinfo=sch.tz)
    if slot > local:
        slot = datetime.combine(d - timedelta(days=7), time(sch.hour, sch.minute), tzinfo=sch.tz)
    return slot


def next_slot(now, sch: Schedule) -> datetime:
    slot = last_slot(now, sch)
    return datetime.combine(slot.date() + timedelta(days=7), time(sch.hour, sch.minute), tzinfo=sch.tz)


def due_period(now, sch: Schedule, grace: timedelta = GRACE) -> str | None:
    """The week's id (the slot's local date) when the digest should go out now, else None."""
    if not sch.enabled:
        return None
    slot = last_slot(now, sch)
    return slot.date().isoformat() if _aware(now) - slot <= grace else None


# ---- text ------------------------------------------------------------------------------------------
def _ts(v) -> datetime | None:
    try:
        return _aware(v)
    except (ValueError, TypeError):
        return None


def _when(v) -> str:
    t = pd.Timestamp(str(v)[:10])
    return f"{t.day} {t.strftime('%b')}"


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:+.1f}%"


def _syms(xs: list[str], n: int = 5) -> str:
    return ", ".join(xs[:n]) + (f" +{len(xs) - n} more" if len(xs) > n else "")


def week_events(events: list[dict], now, days: int = 7) -> list[dict]:
    since = _aware(now) - timedelta(days=days)
    return [e for e in events if (t := _ts(e.get("created_at"))) is not None and since < t <= _aware(now)]


def picks_line(events: list[dict], now) -> str:
    recent = [e for e in events
              if e.get("date") and (_aware(now).date() - pd.Timestamp(str(e["date"])[:10]).date()).days <= 35]
    if not recent:
        return "Picks: no change this week. The list is reviewed at each month end."
    e = recent[0]   # newest first
    parts = [f"buy {_syms(e.get('buy') or [])}" if e.get("buy") else "",
             f"sell {_syms(e.get('sell') or [])}" if e.get("sell") else ""]
    return f"Picks changed (review of {_when(e['date'])}): " + "; ".join(p for p in parts if p) + "."


def alert_phrase(e: dict) -> str:
    kind, v = e.get("kind"), e.get("value")
    if kind == "move":
        chg = e.get("change_pct")
        return f"{e['symbol']} moved {chg:+.1f}%" if isinstance(chg, (int, float)) else f"{e['symbol']} moved {v:g}%+"
    return f"{e['symbol']} {'above' if kind == 'above' else 'below'} {float(v):g}"


def alerts_line(events: list[dict]) -> str:
    if not events:
        return "Your price alerts: none fired this week."
    phrases = [alert_phrase(e) for e in events[:4]]
    more = f" and {len(events) - 4} more" if len(events) > 4 else ""
    return f"Your price alerts: {len(events)} fired ({'; '.join(phrases)}{more})."


def track_line(t: dict | None) -> str:
    if not t:
        return "Live track record: unavailable right now."
    if not t.get("started"):
        return "Live track record: starts after the next US market close."
    p, i = t.get("picks") or {}, t.get("ideas") or {}
    days = int(t.get("days") or 0)
    if days and p.get("return_%") is not None:
        verdict = "ahead of" if p["return_%"] > (p.get("spy_%") or 0) else "behind"
        s = (f"Live track record since {_when(t['started'])} ({days} trading day{'s' if days != 1 else ''}): "
             f"picks {_pct(p['return_%'])} vs S&P 500 {_pct(p.get('spy_%'))} ({verdict}).")
    else:
        s = f"Live track record: started {_when(t['started'])}, no result yet."
    if i.get("closed_count"):
        s += (f" Invest-now ideas: {i['closed_count']} closed, {i.get('win_rate') or 0:.0f}% winners, "
              f"average {i.get('avg_r') or 0:+.2f}R.")
    if t.get("too_early", True):
        s += " Too early to judge: it takes months."
    return s


def drift_line(d: dict | None) -> str | None:
    if not d or d.get("status") not in ("on_target", "drifted"):
        return None
    if d["status"] == "on_target":
        return f"Portfolio: on plan (largest gap {d['max_drift']:.1f} points)."
    return f"Portfolio drift: about {d['total_drift']:.0f}% of your money is off plan. {d.get('suggestion') or ''}".strip()


def mood_line(m: dict | None) -> str:
    if not m:
        return "Market mood: unavailable right now."
    return f"Market mood: {m['label']}. {m.get('advice') or ''}".strip()


def compose(now, picks_events: list[dict], alert_events: list[dict], track: dict | None, mood: dict | None,
            drift: dict | None = None, max_chars: int = MAX_CHARS, timezone: str = "Europe/Paris") -> str:
    """The digest text. Events are newest first and already limited to the past week."""
    local = _aware(now).astimezone(ZoneInfo(timezone))
    head = f"MAYAROSERO weekly digest · {local.day} {local.strftime('%b %Y')}"
    lines = [head, mood_line(mood), picks_line(picks_events, now), alerts_line(alert_events), track_line(track)]
    d = drift_line(drift)
    if d:
        lines.append(d)
    foot = "Details in the app. Information, not advice."
    text = "\n".join(lines + [foot])
    while len(text) > max_chars and len(lines) > 1:   # trim the longest line until it fits
        i = max(range(1, len(lines)), key=lambda k: len(lines[k]))
        room = max(40, len(lines[i]) - (len(text) - max_chars) - 1)
        lines[i] = lines[i][:room].rstrip() + "…"
        text = "\n".join(lines + [foot])
        if room == 40:
            break
    return text[:max_chars]
