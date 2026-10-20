"""Stock universe, organized like a broker's "Discover" section.

Two layers:
- a curated list of well-known stocks with themes ("Magnificent 7", "AI & chips", ...),
  including non-S&P names from Europe and Asia;
- every other current S&P 500 member, loaded from the bundled `data/sp500.csv`
  (symbol, name, GICS sector, short industry). Curated entries win on overlap.

Sectors follow GICS. `sp500` marks current S&P 500 members (used by the picker).
Keep tickers in Yahoo Finance format (BRK-B, BF-B, MC.PA, ...). To refresh the index
list, edit the CSV (one row per member, renames included) and run the tests.

Note: this is today's list. Backtesting a stock picker on today's index members
has survivorship bias (yesterday's losers that left the index are missing), so
historical results look better than reality. The UI states this explicitly.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from importlib import resources


@dataclass(frozen=True)
class Stock:
    symbol: str
    name: str
    sector: str
    industry: str
    region: str = "US"
    sp500: bool = True
    themes: tuple[str, ...] = field(default_factory=tuple)


TECH, COMM, DISC, STAPLES, HEALTH, FIN, IND, ENERGY, MAT, UTIL, RE = (
    "Information Technology", "Communication Services", "Consumer Discretionary", "Consumer Staples",
    "Health Care", "Financials", "Industrials", "Energy", "Materials", "Utilities", "Real Estate")

M7, AI, POP, DIV, LUX, DEF, CLEAN, PAY, BIO, CLOUD, EV = (
    "Magnificent 7", "AI & Semiconductors", "Most popular", "Dividend champions", "Luxury",
    "Defense & Aerospace", "Clean energy", "Payments", "Biotech & Pharma", "Cloud & Software", "Electric vehicles")

_S = Stock
CURATED: list[Stock] = [
    # Information Technology
    _S("AAPL", "Apple", TECH, "Consumer electronics", themes=(M7, POP)),
    _S("MSFT", "Microsoft", TECH, "Software", themes=(M7, POP, AI, CLOUD)),
    _S("NVDA", "NVIDIA", TECH, "Semiconductors", themes=(M7, POP, AI)),
    _S("AVGO", "Broadcom", TECH, "Semiconductors", themes=(AI, POP)),
    _S("AMD", "AMD", TECH, "Semiconductors", themes=(AI, POP)),
    _S("ORCL", "Oracle", TECH, "Software", themes=(AI, CLOUD)),
    _S("CRM", "Salesforce", TECH, "Software", themes=(CLOUD,)),
    _S("ADBE", "Adobe", TECH, "Software", themes=(CLOUD,)),
    _S("CSCO", "Cisco", TECH, "Networking", themes=(DIV,)),
    _S("INTC", "Intel", TECH, "Semiconductors", themes=(AI,)),
    _S("QCOM", "Qualcomm", TECH, "Semiconductors", themes=(AI,)),
    _S("TXN", "Texas Instruments", TECH, "Semiconductors", themes=(DIV,)),
    _S("MU", "Micron", TECH, "Semiconductors", themes=(AI,)),
    _S("AMAT", "Applied Materials", TECH, "Semiconductor equipment", themes=(AI,)),
    _S("LRCX", "Lam Research", TECH, "Semiconductor equipment", themes=(AI,)),
    _S("KLAC", "KLA", TECH, "Semiconductor equipment", themes=(AI,)),
    _S("IBM", "IBM", TECH, "IT services", themes=(AI, DIV)),
    _S("ACN", "Accenture", TECH, "IT services"),
    _S("NOW", "ServiceNow", TECH, "Software", themes=(CLOUD, AI)),
    _S("INTU", "Intuit", TECH, "Software", themes=(CLOUD,)),
    _S("PANW", "Palo Alto Networks", TECH, "Cybersecurity", themes=(CLOUD,)),
    _S("CRWD", "CrowdStrike", TECH, "Cybersecurity", themes=(CLOUD,)),
    _S("PLTR", "Palantir", TECH, "Software", themes=(AI, POP, DEF)),
    _S("ANET", "Arista Networks", TECH, "Networking", themes=(AI,)),
    _S("SNPS", "Synopsys", TECH, "Software", themes=(AI,)),
    _S("CDNS", "Cadence Design", TECH, "Software", themes=(AI,)),
    _S("DELL", "Dell Technologies", TECH, "Hardware", themes=(AI,)),
    _S("SMCI", "Super Micro Computer", TECH, "Hardware", themes=(AI,)),
    # Communication Services
    _S("GOOGL", "Alphabet", COMM, "Internet", themes=(M7, POP, AI)),
    _S("META", "Meta Platforms", COMM, "Internet", themes=(M7, POP, AI)),
    _S("NFLX", "Netflix", COMM, "Streaming", themes=(POP,)),
    _S("DIS", "Walt Disney", COMM, "Entertainment", themes=(POP,)),
    _S("CMCSA", "Comcast", COMM, "Media"),
    _S("T", "AT&T", COMM, "Telecom", themes=(DIV,)),
    _S("VZ", "Verizon", COMM, "Telecom", themes=(DIV,)),
    _S("TMUS", "T-Mobile US", COMM, "Telecom"),
    # Consumer Discretionary
    _S("AMZN", "Amazon", DISC, "E-commerce", themes=(M7, POP, CLOUD)),
    _S("TSLA", "Tesla", DISC, "Automobiles", themes=(M7, POP, EV, CLEAN)),
    _S("HD", "Home Depot", DISC, "Home improvement", themes=(DIV,)),
    _S("MCD", "McDonald's", DISC, "Restaurants", themes=(DIV, POP)),
    _S("NKE", "Nike", DISC, "Apparel", themes=(POP,)),
    _S("SBUX", "Starbucks", DISC, "Restaurants", themes=(POP,)),
    _S("LOW", "Lowe's", DISC, "Home improvement", themes=(DIV,)),
    _S("BKNG", "Booking Holdings", DISC, "Travel"),
    _S("ABNB", "Airbnb", DISC, "Travel", themes=(POP,)),
    _S("UBER", "Uber", DISC, "Mobility", themes=(POP,)),
    _S("CMG", "Chipotle", DISC, "Restaurants"),
    _S("TJX", "TJX Companies", DISC, "Retail"),
    _S("GM", "General Motors", DISC, "Automobiles", themes=(EV,)),
    _S("F", "Ford", DISC, "Automobiles", themes=(EV,)),
    # Consumer Staples
    _S("WMT", "Walmart", STAPLES, "Retail", themes=(POP,)),
    _S("COST", "Costco", STAPLES, "Retail", themes=(POP,)),
    _S("PG", "Procter & Gamble", STAPLES, "Household products", themes=(DIV,)),
    _S("KO", "Coca-Cola", STAPLES, "Beverages", themes=(DIV, POP)),
    _S("PEP", "PepsiCo", STAPLES, "Beverages", themes=(DIV,)),
    _S("PM", "Philip Morris", STAPLES, "Tobacco", themes=(DIV,)),
    _S("MO", "Altria", STAPLES, "Tobacco", themes=(DIV,)),
    _S("MDLZ", "Mondelez", STAPLES, "Food"),
    _S("CL", "Colgate-Palmolive", STAPLES, "Household products", themes=(DIV,)),
    # Health Care
    _S("LLY", "Eli Lilly", HEALTH, "Pharmaceuticals", themes=(BIO, POP)),
    _S("UNH", "UnitedHealth", HEALTH, "Health insurance"),
    _S("JNJ", "Johnson & Johnson", HEALTH, "Pharmaceuticals", themes=(BIO, DIV)),
    _S("ABBV", "AbbVie", HEALTH, "Pharmaceuticals", themes=(BIO, DIV)),
    _S("MRK", "Merck", HEALTH, "Pharmaceuticals", themes=(BIO, DIV)),
    _S("PFE", "Pfizer", HEALTH, "Pharmaceuticals", themes=(BIO, DIV)),
    _S("TMO", "Thermo Fisher", HEALTH, "Life sciences tools"),
    _S("ABT", "Abbott", HEALTH, "Medical devices", themes=(DIV,)),
    _S("ISRG", "Intuitive Surgical", HEALTH, "Medical devices", themes=(AI,)),
    _S("AMGN", "Amgen", HEALTH, "Biotechnology", themes=(BIO,)),
    _S("GILD", "Gilead", HEALTH, "Biotechnology", themes=(BIO,)),
    _S("VRTX", "Vertex", HEALTH, "Biotechnology", themes=(BIO,)),
    _S("REGN", "Regeneron", HEALTH, "Biotechnology", themes=(BIO,)),
    _S("BMY", "Bristol-Myers Squibb", HEALTH, "Pharmaceuticals", themes=(BIO, DIV)),
    # Financials
    _S("BRK-B", "Berkshire Hathaway", FIN, "Conglomerate", themes=(POP,)),
    _S("JPM", "JPMorgan Chase", FIN, "Banks", themes=(DIV, POP)),
    _S("BAC", "Bank of America", FIN, "Banks"),
    _S("WFC", "Wells Fargo", FIN, "Banks"),
    _S("GS", "Goldman Sachs", FIN, "Investment banking"),
    _S("MS", "Morgan Stanley", FIN, "Investment banking"),
    _S("C", "Citigroup", FIN, "Banks"),
    _S("BLK", "BlackRock", FIN, "Asset management", themes=(DIV,)),
    _S("SCHW", "Charles Schwab", FIN, "Brokerage"),
    _S("V", "Visa", FIN, "Payments", themes=(PAY, POP)),
    _S("MA", "Mastercard", FIN, "Payments", themes=(PAY,)),
    _S("AXP", "American Express", FIN, "Payments", themes=(PAY,)),
    _S("PYPL", "PayPal", FIN, "Payments", themes=(PAY,)),
    _S("SPGI", "S&P Global", FIN, "Financial data"),
    _S("COIN", "Coinbase", FIN, "Crypto exchange", themes=(POP,)),
    # Industrials
    _S("GE", "GE Aerospace", IND, "Aerospace", themes=(DEF,)),
    _S("CAT", "Caterpillar", IND, "Machinery", themes=(DIV,)),
    _S("RTX", "RTX", IND, "Aerospace & defense", themes=(DEF,)),
    _S("LMT", "Lockheed Martin", IND, "Aerospace & defense", themes=(DEF, DIV)),
    _S("NOC", "Northrop Grumman", IND, "Aerospace & defense", themes=(DEF,)),
    _S("GD", "General Dynamics", IND, "Aerospace & defense", themes=(DEF,)),
    _S("BA", "Boeing", IND, "Aerospace", themes=(DEF, POP)),
    _S("HON", "Honeywell", IND, "Conglomerate"),
    _S("UNP", "Union Pacific", IND, "Railroads", themes=(DIV,)),
    _S("UPS", "UPS", IND, "Logistics", themes=(DIV,)),
    _S("DE", "Deere", IND, "Machinery"),
    _S("ETN", "Eaton", IND, "Electrical equipment", themes=(AI, CLEAN)),
    # Energy
    _S("XOM", "Exxon Mobil", ENERGY, "Oil & gas", themes=(DIV,)),
    _S("CVX", "Chevron", ENERGY, "Oil & gas", themes=(DIV,)),
    _S("COP", "ConocoPhillips", ENERGY, "Oil & gas"),
    _S("SLB", "SLB", ENERGY, "Oil services"),
    _S("FSLR", "First Solar", ENERGY, "Solar", themes=(CLEAN,)),
    # Materials
    _S("LIN", "Linde", MAT, "Industrial gases", themes=(DIV,)),
    _S("SHW", "Sherwin-Williams", MAT, "Chemicals"),
    _S("FCX", "Freeport-McMoRan", MAT, "Copper mining", themes=(CLEAN,)),
    _S("NEM", "Newmont", MAT, "Gold mining"),
    # Utilities
    _S("NEE", "NextEra Energy", UTIL, "Renewable utilities", themes=(CLEAN, DIV)),
    _S("DUK", "Duke Energy", UTIL, "Electric utilities", themes=(DIV,)),
    _S("SO", "Southern Company", UTIL, "Electric utilities", themes=(DIV,)),
    _S("CEG", "Constellation Energy", UTIL, "Nuclear power", themes=(AI, CLEAN)),
    # Real Estate
    _S("PLD", "Prologis", RE, "Industrial REIT", themes=(DIV,)),
    _S("AMT", "American Tower", RE, "Tower REIT", themes=(DIV,)),
    _S("EQIX", "Equinix", RE, "Data center REIT", themes=(AI, DIV)),
    _S("O", "Realty Income", RE, "Retail REIT", themes=(DIV,)),
    # Europe
    _S("ASML", "ASML", TECH, "Semiconductor equipment", "Europe", False, (AI, POP)),
    _S("SAP", "SAP", TECH, "Software", "Europe", False, (CLOUD,)),
    _S("MC.PA", "LVMH", DISC, "Luxury goods", "Europe", False, (LUX, POP)),
    _S("RMS.PA", "Hermès", DISC, "Luxury goods", "Europe", False, (LUX,)),
    _S("KER.PA", "Kering", DISC, "Luxury goods", "Europe", False, (LUX,)),
    _S("OR.PA", "L'Oréal", STAPLES, "Personal care", "Europe", False, (LUX,)),
    _S("RACE", "Ferrari", DISC, "Automobiles", "Europe", False, (LUX, POP)),
    _S("AIR.PA", "Airbus", IND, "Aerospace", "Europe", False, (DEF,)),
    _S("SAF.PA", "Safran", IND, "Aerospace", "Europe", False, (DEF,)),
    _S("RHM.DE", "Rheinmetall", IND, "Defense", "Europe", False, (DEF,)),
    _S("TTE", "TotalEnergies", ENERGY, "Oil & gas", "Europe", False, (DIV,)),
    _S("SHEL", "Shell", ENERGY, "Oil & gas", "Europe", False, (DIV,)),
    _S("NVO", "Novo Nordisk", HEALTH, "Pharmaceuticals", "Europe", False, (BIO, POP)),
    _S("AZN", "AstraZeneca", HEALTH, "Pharmaceuticals", "Europe", False, (BIO,)),
    _S("SAN.PA", "Sanofi", HEALTH, "Pharmaceuticals", "Europe", False, (BIO, DIV)),
    _S("NESN.SW", "Nestlé", STAPLES, "Food", "Europe", False, (DIV,)),
    _S("BNP.PA", "BNP Paribas", FIN, "Banks", "Europe", False, (DIV,)),
    _S("SIE.DE", "Siemens", IND, "Conglomerate", "Europe", False),
    _S("ITX.MC", "Inditex", DISC, "Apparel", "Europe", False, (POP,)),
    _S("SAN.MC", "Banco Santander", FIN, "Banks", "Europe", False, (DIV,)),
    _S("IBE.MC", "Iberdrola", UTIL, "Renewable utilities", "Europe", False, (CLEAN, DIV)),
    # Asia
    _S("TSM", "TSMC", TECH, "Semiconductors", "Asia", False, (AI, POP)),
    _S("BABA", "Alibaba", DISC, "E-commerce", "Asia", False, (CLOUD,)),
    _S("TM", "Toyota", DISC, "Automobiles", "Asia", False, (EV,)),
    _S("SONY", "Sony", TECH, "Consumer electronics", "Asia", False),
]

CRYPTO = [
    ("BTC/USDT", "Bitcoin"), ("ETH/USDT", "Ethereum"), ("SOL/USDT", "Solana"), ("BNB/USDT", "BNB"),
    ("XRP/USDT", "XRP"), ("ADA/USDT", "Cardano"), ("DOGE/USDT", "Dogecoin"), ("AVAX/USDT", "Avalanche"),
    ("LINK/USDT", "Chainlink"), ("DOT/USDT", "Polkadot"),
]

SECTORS = [TECH, COMM, DISC, STAPLES, HEALTH, FIN, IND, ENERGY, MAT, UTIL, RE]
THEMES = [POP, M7, AI, CLOUD, PAY, DEF, LUX, BIO, DIV, CLEAN, EV]


def load_sp500() -> list[Stock]:
    """Current S&P 500 members from the bundled CSV (region US, no themes)."""
    text = resources.files("tradebot.data").joinpath("sp500.csv").read_text(encoding="utf-8")
    out = []
    for row in csv.DictReader(text.splitlines()):
        if row["sector"] not in SECTORS:
            raise ValueError(f"sp500.csv: unknown sector {row['sector']!r} for {row['symbol']}")
        out.append(Stock(row["symbol"].strip(), row["name"].strip(), row["sector"], row["industry"].strip()))
    return out


def _merge(curated: list[Stock], members: list[Stock]) -> list[Stock]:
    """Curated stocks first (unchanged), then every S&P 500 member not already curated."""
    known = {s.symbol for s in curated}
    return curated + [s for s in members if s.symbol not in known]


STOCKS: list[Stock] = _merge(CURATED, load_sp500())


def sp500_symbols() -> list[str]:
    return [s.symbol for s in STOCKS if s.sp500]


def by_symbol() -> dict[str, Stock]:
    return {s.symbol: s for s in STOCKS}


def as_dict() -> dict:
    return {
        "sectors": SECTORS,
        "themes": THEMES,
        "stocks": [asdict(s) for s in STOCKS],
        "crypto": [{"symbol": s, "name": n, "sector": "Crypto", "industry": "Digital assets",
                    "region": "Global", "sp500": False, "themes": []} for s, n in CRYPTO],
    }
