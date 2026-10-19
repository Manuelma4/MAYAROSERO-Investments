import pandas as pd

from tradebot.live import PaperBroker, closed_bars
from tradebot.live.scanner import Scanner, WatchItem


class Collect:
    def __init__(self):
        self.msgs = []

    def send(self, text):
        self.msgs.append(text)


def test_closed_bars_drops_forming_candle(ohlcv):
    now = ohlcv.index[-1] + pd.Timedelta(hours=3)
    assert len(closed_bars(ohlcv, "1d", now)) == len(ohlcv) - 1
    now = ohlcv.index[-1] + pd.Timedelta(days=1)
    assert len(closed_bars(ohlcv, "1d", now)) == len(ohlcv)


def test_paper_broker_roundtrip(tmp_path):
    b = PaperBroker(tmp_path / "s.json", capital=10_000, fee=0)
    pos = b.open("BTC/USDT", "x", "long", 100.0, 90.0, 120.0, "t0")
    assert pos.qty == 10
    rec = b.check_exits("BTC/USDT", "x", pd.Series({"high": 121, "low": 95}), "t1")
    assert rec["reason"] == "target" and rec["pnl"] == 200
    assert PaperBroker(tmp_path / "s.json").cash == 10_200


def test_scanner_dedupes(ohlcv, tmp_path):
    note = Collect()
    item = WatchItem("yahoo", "TEST", "1d", [{"name": "ema_cross_rsi"}])
    sc = Scanner([item], [note], PaperBroker(tmp_path / "s.json"))
    # Replay history bar by bar like the live loop would see it.
    total = 0
    for i in range(300, 600):
        total += len(sc.check(item, ohlcv.iloc[:i]))
        sc.check(item, ohlcv.iloc[:i])  # same bar again -> no duplicate alerts
    assert sum(m.startswith("[SIGNAL]") for m in note.msgs) == total


def test_detect_move_surge_and_quiet():
    import numpy as np

    from tradebot.live.movers import MoveSettings, MoversScanner, detect_move
    from conftest import make_ohlcv

    s = MoveSettings(timeframe="5m")
    df = make_ohlcv(200, seed=3, drift=0, vol=0.002, freq="5min", cycle=0)
    assert detect_move(df, s) is None  # normal noise is ignored

    spike = df.copy()
    for k, mult in zip(range(-3, 0), (1.01, 1.025, 1.04)):
        spike.iloc[k, spike.columns.get_loc("close")] = df["close"].iloc[-4] * mult
        spike.iloc[k, spike.columns.get_loc("high")] = df["close"].iloc[-4] * mult * 1.001
        spike.iloc[k, spike.columns.get_loc("volume")] *= 5
    m = detect_move(spike, s)
    assert m["direction"] == "SURGE" and m["move_pct"] > 3 and m["zscore"] > 3

    crash = df.copy()
    crash.iloc[-1, crash.columns.get_loc("close")] = df["close"].iloc[-4] * 0.95
    crash.iloc[-1, crash.columns.get_loc("volume")] = df["volume"].mean() * 10
    assert detect_move(crash, s)["direction"] == "CRASH"

    no_volume = df.copy()
    no_volume.iloc[-1, no_volume.columns.get_loc("close")] = df["close"].iloc[-4] * 0.95
    assert detect_move(no_volume, s) is None  # price move without volume is not confirmed

    sc = MoversScanner(s)
    assert len(sc.scan_frames({"X": spike})) == 1
    assert len(sc.scan_frames({"X": spike})) == 0  # deduplicated
