"""Elliott wave helpers.

Elliott wave counting is subjective, so this module does not claim to "find
the count". It labels zigzag swings and checks candidate 5-wave impulses
against the three hard rules, plus common Fibonacci guidelines. Use it as a
filter or as a research tool, not as a standalone signal.

Hard rules (bullish impulse, points p0..p5):
1. Wave 2 never retraces more than 100% of wave 1   (p2 > p0)
2. Wave 3 is never the shortest of waves 1, 3 and 5
3. Wave 4 does not overlap wave 1's territory        (p4 > p1)
"""

from __future__ import annotations

import pandas as pd

from .swings import zigzag


def check_impulse(p: list[float]) -> dict:
    """Validate 6 alternating points p0..p5 as an impulse (bull or bear)."""
    if len(p) != 6:
        raise ValueError("need 6 points")
    bull = p[1] > p[0]
    s = 1 if bull else -1
    w1, w3, w5 = s * (p[1] - p[0]), s * (p[3] - p[2]), s * (p[5] - p[4])
    w2, w4 = s * (p[1] - p[2]), s * (p[3] - p[4])
    rules = {
        "wave2_within_wave1": s * (p[2] - p[0]) > 0,
        "wave3_not_shortest": not (w3 < w1 and w3 < w5),
        "wave4_no_overlap": s * (p[4] - p[1]) > 0,
        "alternating": all(x > 0 for x in (w1, w2, w3, w4, w5)),
    }
    guidelines = {
        "wave2_retrace": w2 / w1 if w1 else None,       # typical 0.5-0.618
        "wave3_extension": w3 / w1 if w1 else None,     # typical >= 1.618
        "wave4_retrace": w4 / w3 if w3 else None,       # typical 0.236-0.382
    }
    return {"direction": "bull" if bull else "bear", "valid": all(rules.values()),
            "rules": rules, "guidelines": guidelines}


def find_impulses(df: pd.DataFrame, pct: float = 0.05) -> list[dict]:
    """Scan consecutive zigzag swings for rule-valid 5-wave impulses."""
    zz = zigzag(df, pct)
    found = []
    for i in range(len(zz) - 5):
        pts = zz.iloc[i:i + 6]
        res = check_impulse(pts["price"].tolist())
        if res["valid"]:
            res["start"], res["end"] = pts["time"].iloc[0], pts["time"].iloc[-1]
            res["points"] = pts["price"].tolist()
            found.append(res)
    return found
