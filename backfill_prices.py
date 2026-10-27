"""Backfill official TWSE/TPEx daily prices for a date range in one transaction.

Usage: python -m backfill_prices --start 2026-08-27 --end 2026-10-21
Non-trading days (TWSE/TPEx return no data for the date) are skipped.
Re-running is idempotent: existing rows for the fetched (date, symbol) keys are replaced.
"""

from __future__ import annotations

import argparse
import time
from datetime import date, timedelta

from sqlalchemy import text

from pipeline.sources import SourceError, fetch_tpex_prices, fetch_twse_prices
from snapshot_sync import LOCK_NAME, REQUIRED_PRICE_COLUMNS, _insert_rows

PRICE_COLUMNS = sorted(REQUIRED_PRICE_COLUMNS)


def fetch_range(start: date, end: date, *, pause: float = 2.5) -> dict[str, list[dict]]:
    output: dict[str, list[dict]] = {}
    day = start
    while day <= end:
        if day.weekday() < 5:
            try:
                twse, _ = fetch_twse_prices(day)
                time.sleep(pause)
                tpex, _ = fetch_tpex_prices(day)
                time.sleep(pause)
            except SourceError:
                day += timedelta(days=1)
                continue
            output[day.isoformat()] = twse + tpex
        day += timedelta(days=1)
    return output


def apply_prices(engine, by_day: dict[str, list[dict]]) -> int:
    total = 0
    with engine.begin() as conn:
        if not conn.execute(text("SELECT pg_try_advisory_xact_lock(hashtext(:name))"), {"name": LOCK_NAME}).scalar():
            raise RuntimeError("snapshot sync lock is busy")
        for day, rows in sorted(by_day.items()):
            symbols = [row["symbol"] for row in rows]
            if len(symbols) != len(set(symbols)):
                raise ValueError(f"duplicate symbols on {day}")
            conn.execute(
                text("DELETE FROM stock_prices WHERE date::date=:day AND symbol=ANY(:symbols)"),
                {"day": date.fromisoformat(day), "symbols": symbols},
            )
            total += _insert_rows(conn, "stock_prices", PRICE_COLUMNS, rows)
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--database-url", required=True, help="PostgreSQL URL; never commit it")
    args = parser.parse_args()
    from sqlalchemy import create_engine

    by_day = fetch_range(args.start, args.end)
    rows = apply_prices(create_engine(args.database_url), by_day)
    print(f"days={len(by_day)} rows={rows}")


if __name__ == "__main__":
    main()
