# scripts/download_aapl_yfinance.py

from __future__ import annotations

import csv
from pathlib import Path

import yfinance as yf


def main() -> None:
    """
    Download recent AAPL intraday data from Yahoo Finance and save it as
    data/aapl_1m.csv with columns:

        timestamp,bid,ask,last

    We only have 'Close' from Yahoo, so we map:
        last = Close
        bid/ask = empty (None in the loader).
    """

    symbol = "AAPL"

    # For 1-minute bars, Yahoo only allows a short recent window.
    # '5d' + '1m' is usually accepted.
    period = "5d"
    interval = "1m"

    print(f"Downloading {symbol} {interval} data for last {period} ...")
    df = yf.download(
        symbol,
        period=period,
        interval=interval,
        progress=False,
    )

    if df.empty:
        raise RuntimeError(
            "No data returned from yfinance. "
            "Try changing 'period' or 'interval' (e.g. period='60d', interval='5m' "
            "or period='1y', interval='1d')."
        )

    out_path = Path("data") / "aapl_1m.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "bid", "ask", "last"])

        for ts, row in df.iterrows():
            ts_str = ts.isoformat()
            last = float(row["Close"])
            writer.writerow([ts_str, "", "", f"{last:.4f}"])

    print(f"Wrote {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()
