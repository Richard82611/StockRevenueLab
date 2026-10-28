"""CI step: apply the sealed snapshot straight to PostgreSQL, filling missed trading days first.

Reads the connection string from the DATABASE_URL environment variable (set from the
GitHub Actions secret). When it is missing or empty the step logs a skip and exits 0,
so the snapshot commit workflow keeps working without database access.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable

from sqlalchemy import text

from pipeline.snapshot import read_snapshot

SKIP_MESSAGE = "[db-apply] DATABASE_URL secret is not set; skipping direct database write."
AGGREGATE_TABLES = ("stock_weekly_k", "stock_monthly_k", "stock_annual_k")


def _months_between(start: date, end: date) -> Iterable[tuple[int, int]]:
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        month += 1
        if month > 12:
            year, month = year + 1, 1


def gap_trading_days(
    db_max: date | None,
    snapshot_date: date,
    fetch_month: Callable[[int, int], list[date]],
) -> list[date]:
    """Official trading days strictly after db_max and strictly before snapshot_date."""
    if db_max is None or db_max >= snapshot_date - timedelta(days=1):
        return []
    start = db_max + timedelta(days=1)
    end = snapshot_date - timedelta(days=1)
    days: list[date] = []
    for year, month in _months_between(start, end):
        days.extend(day for day in fetch_month(year, month) if start <= day <= end)
    return sorted(set(days))


def refresh_aggregates_for_days(engine, by_day: dict[str, list[dict]]) -> dict:
    """Run the app's _refresh_aggregate once per touched week/month/year."""
    from snapshot_sync import _refresh_aggregate, _relation_info

    if not by_day:
        return {}
    results: dict[str, int] = {}
    with engine.begin() as conn:
        relations = _relation_info(conn, list(AGGREGATE_TABLES))
        cutoffs: dict[tuple, tuple[date, set[str]]] = {}
        for day_text, rows in by_day.items():
            day = date.fromisoformat(day_text)
            symbols = {row["symbol"] for row in rows}
            for key in (("w", day.isocalendar()[:2]), ("m", (day.year, day.month)), ("y", day.year)):
                cutoff, existing = cutoffs.get(key, (day, set()))
                cutoffs[key] = (max(cutoff, day), existing | symbols)
        for (kind, _), (cutoff, symbols) in sorted(cutoffs.items(), key=lambda item: str(item[0])):
            table = {"w": "stock_weekly_k", "m": "stock_monthly_k", "y": "stock_annual_k"}[kind]
            results[f"{table}:{cutoff}"] = _refresh_aggregate(
                conn, table_name=table, relation=relations.get(table), symbols=sorted(symbols), cutoff=cutoff
            )
    return results


def _normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def run(
    snapshot_path: Path,
    *,
    environ=os.environ,
    engine_factory=None,
    fetch_month=None,
    fetch_range=None,
    log=print,
) -> int:
    url = (environ.get("DATABASE_URL") or "").strip()
    if not url:
        log(SKIP_MESSAGE)
        return 0
    if engine_factory is None:
        from sqlalchemy import create_engine

        def engine_factory(value):
            return create_engine(value, pool_pre_ping=True, connect_args={"connect_timeout": 15})

    if fetch_month is None:
        from pipeline.sources import fetch_twse_trading_days as fetch_month
    if fetch_range is None:
        from backfill_prices import fetch_days as fetch_range

    from backfill_prices import apply_prices
    from snapshot_sync import apply_snapshot

    payload = read_snapshot(snapshot_path)
    engine = engine_factory(_normalize_url(url))
    with engine.connect() as conn:
        db_max = conn.execute(text("SELECT MAX(date::date) FROM stock_prices")).scalar()
    snapshot_date = date.fromisoformat(payload["price_date"])
    gap = gap_trading_days(db_max, snapshot_date, fetch_month)
    log(f"[db-apply] db_max={db_max} snapshot={snapshot_date} gap_days={[d.isoformat() for d in gap]}")
    if gap:
        by_day = fetch_range(gap)
        missing = [d.isoformat() for d in gap if d.isoformat() not in by_day]
        if missing:
            raise RuntimeError(f"official prices missing for trading days: {missing}")
        rows = apply_prices(engine, by_day)
        aggregates = refresh_aggregates_for_days(engine, by_day)
        log(f"[db-apply] backfilled rows={rows} aggregates={aggregates}")
    result = apply_snapshot(engine, payload)
    log(f"[db-apply] snapshot result={result}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=Path("data/latest_snapshot.json.gz"))
    args = parser.parse_args()
    return run(args.snapshot)


if __name__ == "__main__":
    sys.exit(main())
