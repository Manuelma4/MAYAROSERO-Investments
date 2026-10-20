"""Free news headlines (Yahoo Finance search) and simple catalyst classification.

Research basis: large price moves backed by public news tend to keep drifting in the same
direction, while moves without news tend to partly reverse (Chan, 2003, JFE). So the
opportunity scanner only promotes moves that have a recent, relevant headline.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

CATALYSTS: list[tuple[str, str]] = [
    ("earnings", r"\b(earnings|results|quarter(ly)?|q[1-4]\b|revenue|eps|profit|sales)\b"),
    ("guidance", r"\b(guidance|outlook|forecast|raises|lifts|cuts|lowers)\b"),
    ("analyst", r"\b(upgrade[sd]?|downgrade[sd]?|price target|initiates|overweight|underweight|outperform|buy rating|sell rating)\b"),
    ("deal", r"\b(acquir\w*|acquisition|merger|takeover|buyout|deal|stake)\b"),
    ("contract", r"\b(contract|order|partnership|agreement|awarded|wins)\b"),
    ("product", r"\b(launch\w*|unveil\w*|approval|approved|fda|patent|trial)\b"),
    ("capital", r"\b(buyback|repurchase|dividend|split|offering)\b"),
    ("legal", r"\b(lawsuit|probe|investigation|recall|fine|settlement|sec charges)\b"),
]


@dataclass
class Headline:
    title: str
    publisher: str
    url: str
    published: float  # unix seconds
    catalyst: str | None
    direct: bool = False  # the title names the company or ticker (strong evidence)

    @property
    def strength(self) -> int:
        return (2 if self.direct else 0) + (1 if self.catalyst else 0)


def classify(title: str) -> str | None:
    t = title.lower()
    for name, pattern in CATALYSTS:
        if re.search(pattern, t):
            return name
    return None


GENERIC = {"inc", "corp", "corporation", "company", "holdings", "group", "technologies", "technology", "energy",
           "international", "financial", "systems", "the", "and", "platforms", "global", "industries", "motors",
           "communications", "entertainment", "health", "networks", "design", "materials", "computer", "bank"}


def name_tokens(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9&']+", name.lower()) if len(w) >= 4 and w not in GENERIC}


def mentions(title: str, symbol: str, name: str | None) -> bool:
    base = symbol.split("/")[0].replace("^", "")
    t = title.lower()
    if len(base) >= 2 and re.search(rf"\b{re.escape(base.lower())}\b", t):
        return True
    return bool(name and any(re.search(rf"\b{re.escape(w)}\b", t) for w in name_tokens(name)))


def is_relevant(title: str, related: list[str] | None, symbol: str, name: str | None) -> bool:
    """Counts if the title names the company/ticker, or Yahoo tags the ticker AND it's a real catalyst."""
    if mentions(title, symbol, name):
        return True
    base = symbol.split("/")[0].replace("^", "").upper()
    return bool(related and base in {r.upper() for r in related} and classify(title))


def parse_items(items: list[dict], symbol: str, max_age_hours: float, now: float | None = None,
                name: str | None = None) -> list[Headline]:
    """Keep recent headlines that are actually about `symbol`."""
    now = now or time.time()
    out = []
    for it in items:
        content = it.get("content") if isinstance(it.get("content"), dict) else it
        title = content.get("title") or ""
        ts = content.get("providerPublishTime") or content.get("pubDate")
        if isinstance(ts, str):
            try:
                from datetime import datetime

                ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = None
        if not title or not ts or now - float(ts) > max_age_hours * 3600:
            continue
        related = it.get("relatedTickers") or content.get("relatedTickers")
        if not is_relevant(title, related, symbol, name):
            continue
        provider = content.get("publisher") or (content.get("provider") or {}).get("displayName", "")
        url = content.get("link") or (content.get("canonicalUrl") or {}).get("url", "")
        out.append(Headline(title, provider, url, float(ts), classify(title), mentions(title, symbol, name)))
    return sorted(out, key=lambda h: (-h.strength, -h.published))


class NewsSource:
    """Yahoo Finance news via yfinance's search endpoint, cached per symbol."""

    def __init__(self, ttl: int = 900):
        self.ttl = ttl
        self._cache: dict[str, tuple[float, list[dict]]] = {}

    def headlines(self, symbol: str, max_age_hours: float = 36, name: str | None = None) -> list[Headline]:
        now = time.time()
        hit = self._cache.get(symbol)
        if hit and now - hit[0] < self.ttl:
            items = hit[1]
        else:
            try:
                import yfinance as yf

                from ..data.providers import _YF_LOCK

                query = symbol.split("/")[0].replace("^", "")
                with _YF_LOCK:
                    items = yf.Search(query, news_count=10, max_results=1).news or []
            except Exception as exc:
                log.debug("news failed for %s: %s", symbol, exc)
                items = []
            self._cache[symbol] = (now, items)
        return parse_items(items, symbol, max_age_hours, now, name)
