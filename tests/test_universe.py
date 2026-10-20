from tradebot.universe import CURATED, SECTORS, STOCKS, THEMES, as_dict, by_symbol, load_sp500, sp500_symbols


def test_universe_covers_the_sp500():
    syms = [s.symbol for s in STOCKS]
    assert len(syms) == len(set(syms)), "duplicate symbols"
    assert len(sp500_symbols()) >= 495
    assert all(s.sector in SECTORS for s in STOCKS)
    assert all(t in THEMES for s in STOCKS for t in s.themes)
    assert all(s.symbol and s.name and s.industry and s.symbol == s.symbol.strip().upper() for s in STOCKS)
    # Yahoo ticker format for share classes
    assert {"BRK-B", "BF-B", "GOOG", "GOOGL"} <= set(sp500_symbols())


def test_curated_entries_win_and_csv_is_valid():
    members = load_sp500()
    assert len(members) == len({s.symbol for s in members}) >= 495
    info = by_symbol()
    for s in CURATED:  # curated stocks are kept exactly as written (themes, region, sp500 flag)
        assert info[s.symbol] == s
    assert STOCKS[: len(CURATED)] == CURATED
    extra = STOCKS[len(CURATED):]
    assert extra and all(s.sp500 and not s.themes and s.region == "US" for s in extra)
    assert len(as_dict()["stocks"]) == len(STOCKS)
