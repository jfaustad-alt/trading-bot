"""Oslo Børs (Euronext Oslo) stock universe for backtesting.

This file defines the Norwegian stocks and benchmark index used when
backtesting on the Oslo stock exchange. All tickers use the Yahoo
Finance ".OL" suffix.

Oslo Børs (pronounced "børs" like "burse") is Norway's main stock
exchange, now part of Euronext. It's home to major companies in:
    - Energy (Equinor, Aker BP) — Norway is a huge oil/gas producer
    - Seafood (Mowi, SalMar) — world's largest salmon exporters
    - Shipping (Frontline, Hafnia)
    - Finance (DNB, Storebrand)
    - Tech/Telecom (Telenor, Crayon)

Market hours: 09:00 – 16:20 CET (Central European Time).
"""

# The Oslo Benchmark Index — equivalent of SPY for the Norwegian market.
# Used to assess overall market condition (trending, range-bound, breakout).
OSLO_BENCHMARK: str = "OSEBX.OL"

# Liquid Norwegian stocks suitable for backtesting.
# These are among the most traded on Oslo Børs, with good volume
# and price data available through Yahoo Finance.
OSLO_STOCKS: list[str] = [
    # --- Energy (Norway's biggest sector) ---
    "EQNR.OL",    # Equinor — state oil company, Norway's largest
    "AKRBP.OL",   # Aker BP — oil & gas exploration
    "VAR.OL",     # Vår Energi — oil & gas production

    # --- Seafood (Norway = world salmon capital) ---
    "MOWI.OL",    # Mowi — world's largest salmon farmer
    "SALM.OL",    # SalMar — salmon farming
    "LSG.OL",     # Lerøy Seafood — fish and seafood

    # --- Finance ---
    "DNB.OL",     # DNB — Norway's largest bank
    "STB.OL",     # Storebrand — insurance and asset management
    "MORG.OL",    # SpareBank 1 SMN — regional bank

    # --- Telecom & Tech ---
    "TEL.OL",     # Telenor — major Nordic telecom
    "CRAYN.OL",   # Crayon — IT services and cloud

    # --- Shipping & Industry ---
    "FRO.OL",     # Frontline — oil tanker shipping
    "HAFNI.OL",   # Hafnia — product tanker shipping
    "YAR.OL",     # Yara International — fertilizer/chemicals
    "NHY.OL",     # Norsk Hydro — aluminium and energy

    # --- Consumer & Other ---
    "ORK.OL",     # Orkla — consumer goods (food, home care)
    "KOG.OL",     # Kongsberg Gruppen — defence and maritime tech
    "NSKOG.OL",   # Norske Skog — paper and packaging
]
