"""Build the latest official Taiwan-stock snapshot."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline.snapshot import SCHEMA_VERSION, read_snapshot, write_snapshot
from pipeline.sources import fetch_latest_mops_revenue, fetch_latest_official_prices


def build_snapshot(as_of: date | None = None) -> dict:
    price_date, prices, price_sources, price_quality = fetch_latest_official_prices(as_of)
    revenue_month, revenues, revenue_sources, revenue_quality = fetch_latest_mops_revenue(as_of)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": f"{price_date}__{revenue_month}",
        "generated_at": generated_at,
        "price_date": price_date,
        "revenue_month": revenue_month,
        "sources": {
            "prices": price_sources,
            "revenues": revenue_sources,
            "finmind_crosscheck": "NOT_EVALUABLE_FINMIND_TOKEN_NOT_REQUIRED_FOR_OFFICIAL_PIPELINE",
        },
        "quality": {**price_quality, **revenue_quality, "status": "PASS"},
        "prices": prices,
        "revenues": revenues,
    }


def snapshot_changed(path: Path, payload: dict) -> bool:
    if not path.exists():
        return True
    try:
        previous = read_snapshot(path)
    except (OSError, ValueError):
        return True
    volatile = {"generated_at", "sha256"}
    previous_body = {key: value for key, value in previous.items() if key not in volatile}
    current_body = {key: value for key, value in payload.items() if key not in volatile}
    return previous_body != current_body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/latest_snapshot.json.gz"))
    parser.add_argument("--as-of", type=date.fromisoformat)
    args = parser.parse_args()
    payload = build_snapshot(args.as_of)
    changed = snapshot_changed(args.output, payload)
    if changed:
        write_snapshot(args.output, payload)
    print(
        f"snapshot={payload['snapshot_id']} price_rows={payload['quality']['price_rows']} "
        f"revenue_rows={payload['quality']['revenue_rows']} status=PASS changed={str(changed).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
