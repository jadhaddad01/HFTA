# scripts/plot_equity_curve.py

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import matplotlib.pyplot as plt


@dataclass
class EquityPoint:
    timestamp: datetime
    equity: float


def load_equity_csv(path: str) -> List[EquityPoint]:
    points: List[EquityPoint] = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_raw = row["timestamp"]
            eq_raw = row["equity"]
            if not ts_raw or not eq_raw:
                continue
            # Accept ISO8601 or simple string
            try:
                ts = datetime.fromisoformat(ts_raw)
            except ValueError:
                # Fallback: just keep as naive datetime from string
                ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
            equity = float(eq_raw)
            points.append(EquityPoint(timestamp=ts, equity=equity))
    return points


def compute_max_drawdown(equity: List[EquityPoint]) -> Tuple[float, float, float]:
    """
    Return (max_drawdown_pct, peak_equity, trough_equity).
    """
    if not equity:
        return 0.0, 0.0, 0.0

    max_equity = equity[0].equity
    max_drawdown = 0.0
    peak_eq = max_equity
    trough_eq = max_equity

    for pt in equity:
        if pt.equity > max_equity:
            max_equity = pt.equity
        dd = (max_equity - pt.equity) / max_equity if max_equity > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd
            peak_eq = max_equity
            trough_eq = pt.equity

    return max_drawdown * 100.0, peak_eq, trough_eq


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot equity curve and show additional stats."
    )
    parser.add_argument(
        "--equity-csv",
        required=True,
        help="Path to equity CSV produced by scripts.run_backtest.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show matplotlib window (otherwise just print stats).",
    )
    parser.add_argument(
        "--save",
        type=str,
        default=None,
        help="Optional path to save PNG of the equity curve.",
    )

    args = parser.parse_args()

    points = load_equity_csv(args.equity_csv)
    if not points:
        print(f"No equity data found in {args.equity_csv}")
        return

    start_eq = points[0].equity
    end_eq = points[-1].equity
    total_return_pct = (end_eq / start_eq - 1.0) * 100.0 if start_eq > 0 else 0.0

    max_dd_pct, peak_eq, trough_eq = compute_max_drawdown(points)

    print("=== EQUITY ANALYSIS ===")
    print(f"Start equity: {start_eq:,.2f}")
    print(f"End equity:   {end_eq:,.2f}")
    print(f"Total return: {total_return_pct:.4f}%")
    print(f"Max drawdown: {max_dd_pct:.4f}%")
    print(f"Peak equity at DD:   {peak_eq:,.2f}")
    print(f"Trough equity at DD: {trough_eq:,.2f}")
    print(f"Number of points: {len(points)}")

    # Plot
    times = [p.timestamp for p in points]
    equities = [p.equity for p in points]

    plt.figure(figsize=(10, 5))
    plt.plot(times, equities)
    plt.xlabel("Time")
    plt.ylabel("Equity")
    plt.title("Backtest Equity Curve")
    plt.tight_layout()

    if args.save:
        out_path = Path(args.save)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(out_path)
        print(f"Equity curve saved to {out_path}")

    if args.show:
        plt.show()
    else:
        plt.close()


if __name__ == "__main__":
    main()
