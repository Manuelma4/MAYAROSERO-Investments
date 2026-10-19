"""Strategy registry. Add your own setups here."""

from .base import Strategy
from .dow_pullback import DowPullback
from .ema_cross import EmaCrossRsi
from .wyckoff_spring import WyckoffSpring

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (EmaCrossRsi, DowPullback, WyckoffSpring)
}


def get_strategy(name: str, **params) -> Strategy:
    if name not in REGISTRY:
        raise ValueError(f"Unknown strategy '{name}'. Available: {', '.join(REGISTRY)}")
    return REGISTRY[name](params=params)


__all__ = ["Strategy", "REGISTRY", "get_strategy"]
