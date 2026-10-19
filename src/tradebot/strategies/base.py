"""Strategy interface.

A strategy turns OHLCV candles into per-bar decisions. `prepare()` must
return the input frame plus these columns:

    entry_long, entry_short : bool  - setup triggered at this bar's close
    exit_long, exit_short   : bool  - discretionary exit at this bar's close
    stop                    : float - protective stop price for a new entry
    target                  : float - take-profit price (NaN = none)

Rules that keep backtests honest:
- Only use information available at the close of the bar (no `shift(-1)`,
  no centered windows without confirmation delay).
- The engine fills entries at the NEXT bar's open, never at the signal close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np
import pandas as pd


@dataclass
class Strategy:
    name: ClassVar[str] = "base"
    description: ClassVar[str] = ""
    params: dict[str, Any] = field(default_factory=dict)

    defaults: ClassVar[dict[str, Any]] = {}

    def p(self, key: str):
        return self.params.get(key, self.defaults[key])

    def signals(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self.signals(df.copy())
        for col in ("entry_long", "entry_short", "exit_long", "exit_short"):
            out[col] = out.get(col, pd.Series(False, index=out.index)).fillna(False).astype(bool)
        for col in ("stop", "target"):
            if col not in out:
                out[col] = np.nan
        return out
