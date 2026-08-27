"""Idempotently apply a sealed official snapshot to PostgreSQL."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from pipeline.snapshot import read_snapshot


LOCK_NAME = "stockrevenuelab_snapshot_sync_v1"
REQUIRED_PRICE_COLUMNS = {"date", "symbol", "open", "high", "low", "close", "volume"}
REQUIRED_REVENUE_COLUMNS = {"report_month", "stock_id", "stock_name", "mom_pct", "yoy_pct"}


class SnapshotSyncError(RuntimeError):
    pass


def _relation_info(conn, names: list[str]) -> dict[str, dict]:
    relations = {
        row.table_name: {"type": row.relation_type, "columns": set()}
        for row in conn.execute(
            text(
                """
                SELECT c.relname AS table_name,
                       CASE c.relkind WHEN 'r' THEN 'table' WHEN 'v' THEN 'view'
                         WHEN 'm' THEN 'materialized_view' ELSE c.relkind::text END AS relation_type
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname='public' AND c.relname = ANY(:names)
                """
            ),
            {"names": names},
        )
    }
    for row in conn.execute(
        text(
            """
            SELECT table_name,column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name = ANY(:names)
            """
        ),
        {"names": names},
    ):
        if row.table_name in relations:
            relations[row.table_name]["columns"].add(row.column_name)
    return relations


def _ensure_run_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS data_update_runs (
              snapshot_id text PRIMARY KEY,
              generated_at timestamptz NOT NULL,
              price_date date NOT NULL,
              revenue_month text NOT NULL,
              status text NOT NULL,
              applied_at timestamptz NOT NULL DEFAULT now(),
              details jsonb NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )
    )


def _insert_rows(conn, table_name: str, columns: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    quoted = ",".join(f'"{column}"' for column in columns)
    values = ",".join(f":{column}" for column in columns)
    conn.execute(text(f'INSERT INTO "{table_name}" ({quoted}) VALUES ({values})'), rows)


def _upsert_prices(conn, payload: dict, columns: set[str]) -> int:
    missing = REQUIRED_PRICE_COLUMNS - columns
    if missing:
        raise SnapshotSyncError("stock_prices missing columns: " + ",".join(sorted(missing)))
    price_date = date.fromisoformat(payload["price_date"])
    existing_max = conn.execute(text("SELECT MAX(date::date) FROM stock_prices")).scalar()
    if existing_max and existing_max > price_date:
        return 0
    rows = [
        {column: row.get(column) for column in sorted(REQUIRED_PRICE_COLUMNS)}
        for row in payload["prices"]
    ]
    symbols = [row["symbol"] for row in rows]
    conn.execute(
        text("DELETE FROM stock_prices WHERE date::date=:price_date AND symbol=ANY(:symbols)"),
        {"price_date": price_date, "symbols": symbols},
    )
    _insert_rows(conn, "stock_prices", sorted(REQUIRED_PRICE_COLUMNS), rows)
    return len(rows)


def _upsert_revenues(conn, payload: dict, columns: set[str]) -> int:
    missing = REQUIRED_REVENUE_COLUMNS - columns
    if missing:
        raise SnapshotSyncError("monthly_revenue missing columns: " + ",".join(sorted(missing)))
    snapshot_month = payload["revenue_month"]
    existing_max = conn.execute(text("SELECT MAX(report_month)::text FROM monthly_revenue")).scalar()
    if existing_max and existing_max > snapshot_month:
        return 0
    supported = [
        column
        for column in (
            "report_month",
            "market_type",
            "stock_id",
            "stock_name",
            "rev_current",
            "rev_last_month",
            "rev_last_year",
            "mom_pct",
            "yoy_pct",
            "rev_accumulated",
            "rev_accumulated_last_year",
            "yoy_accumulated_pct",
            "remark",
        )
        if column in columns
    ]
    rows = []
    for row in payload["revenues"]:
        item = {column: row.get(column) for column in supported}
        item["stock_id"] = int(row["stock_id"])
        rows.append(item)
    conn.execute(text("DELETE FROM monthly_revenue WHERE report_month=:month"), {"month": snapshot_month})
    _insert_rows(conn, "monthly_revenue", supported, rows)
    return len(rows)


def _refresh_aggregate(
    conn,
    *,
    table_name: str,
    relation: dict | None,
    symbols: list[str],
    cutoff: date,
) -> int:
    if not relation or relation["type"] != "table":
        return 0
    columns = relation["columns"]
    if table_name == "stock_weekly_k":
        required = {"date", "symbol", "w_close"}
        if not required <= columns:
            return 0
        start = cutoff - timedelta(days=cutoff.weekday())
        end = start + timedelta(days=6)
        delete_sql = "DELETE FROM stock_weekly_k WHERE date::date BETWEEN :start AND :end AND symbol=ANY(:symbols)"
        delete_params = {"start": start, "end": end, "symbols": symbols}
        expressions = {
            "date": "MAX(date::date)",
            "symbol": "symbol",
            "w_open": "(array_agg(open ORDER BY date::date))[1]",
            "w_close": "(array_agg(close ORDER BY date::date DESC))[1]",
            "w_high": "MAX(high)",
            "w_low": "MIN(low)",
            "w_volume": "SUM(volume)",
        }
        where_sql = "date::date BETWEEN :start AND :end AND symbol=ANY(:symbols)"
        query_params = delete_params
    elif table_name == "stock_monthly_k":
        required = {"report_month", "symbol", "m_close"}
        if not required <= columns:
            return 0
        roc_month = f"{cutoff.year - 1911}_{cutoff.month:02d}"
        key_value = roc_month
        delete_sql = "DELETE FROM stock_monthly_k WHERE report_month=:key_value AND symbol=ANY(:symbols)"
        delete_params = {"key_value": key_value, "symbols": symbols}
        expressions = {
            "report_month": ":key_value",
            "symbol": "symbol",
            "m_open": "(array_agg(open ORDER BY date::date))[1]",
            "m_close": "(array_agg(close ORDER BY date::date DESC))[1]",
            "m_high": "MAX(high)",
            "m_low": "MIN(low)",
            "m_volume": "SUM(volume)",
        }
        where_sql = "EXTRACT(YEAR FROM date::date)=:year AND EXTRACT(MONTH FROM date::date)=:month AND symbol=ANY(:symbols)"
        query_params = {"key_value": key_value, "year": cutoff.year, "month": cutoff.month, "symbols": symbols}
    elif table_name == "stock_annual_k":
        required = {"year", "symbol", "year_close"}
        if not required <= columns:
            return 0
        key_value = str(cutoff.year)
        delete_sql = "DELETE FROM stock_annual_k WHERE year::text=:key_value AND symbol=ANY(:symbols)"
        delete_params = {"key_value": key_value, "symbols": symbols}
        expressions = {
            "year": ":key_value",
            "symbol": "symbol",
            "first_trade_date": "MIN(date::date)",
            "last_trade_date": "MAX(date::date)",
            "year_open": "(array_agg(open ORDER BY date::date))[1]",
            "year_close": "(array_agg(close ORDER BY date::date DESC))[1]",
            "year_high": "MAX(high)",
            "year_low": "MIN(low)",
            "year_volume": "SUM(volume)",
        }
        where_sql = "EXTRACT(YEAR FROM date::date)=:year AND symbol=ANY(:symbols)"
        query_params = {"key_value": key_value, "year": cutoff.year, "symbols": symbols}
    else:
        return 0

    insert_columns = [column for column in expressions if column in columns]
    if not required <= set(insert_columns):
        return 0
    conn.execute(text(delete_sql), delete_params)
    quoted = ",".join(f'"{column}"' for column in insert_columns)
    selected = ",".join(f'{expressions[column]} AS "{column}"' for column in insert_columns)
    result = conn.execute(
        text(
            f'INSERT INTO "{table_name}" ({quoted}) '
            f'SELECT {selected} FROM stock_prices WHERE {where_sql} GROUP BY symbol'
        ),
        query_params,
    )
    return result.rowcount if result.rowcount and result.rowcount > 0 else 0


def apply_snapshot(engine, payload: dict) -> dict:
    snapshot_id = payload["snapshot_id"]
    details = {
        "price_rows": payload["quality"]["price_rows"],
        "revenue_rows": payload["quality"]["revenue_rows"],
        "sha256": payload["sha256"],
    }
    try:
        with engine.begin() as conn:
            locked = conn.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:name))"), {"name": LOCK_NAME}
            ).scalar()
            if not locked:
                return {"status": "lock_busy", "snapshot_id": snapshot_id}
            _ensure_run_table(conn)
            previous = conn.execute(
                text("SELECT status FROM data_update_runs WHERE snapshot_id=:snapshot_id"),
                {"snapshot_id": snapshot_id},
            ).scalar()
            if previous == "PASS":
                return {"status": "already_applied", "snapshot_id": snapshot_id}

            relations = _relation_info(
                conn,
                ["monthly_revenue", "stock_prices", "stock_weekly_k", "stock_monthly_k", "stock_annual_k"],
            )
            if "monthly_revenue" not in relations or "stock_prices" not in relations:
                raise SnapshotSyncError("required base tables are missing")
            price_rows = _upsert_prices(conn, payload, relations["stock_prices"]["columns"])
            revenue_rows = _upsert_revenues(conn, payload, relations["monthly_revenue"]["columns"])
            symbols = [row["symbol"] for row in payload["prices"]]
            cutoff = date.fromisoformat(payload["price_date"])
            aggregates = {
                table: _refresh_aggregate(
                    conn,
                    table_name=table,
                    relation=relations.get(table),
                    symbols=symbols,
                    cutoff=cutoff,
                )
                for table in ("stock_weekly_k", "stock_monthly_k", "stock_annual_k")
            }
            details.update({"inserted_prices": price_rows, "inserted_revenues": revenue_rows, "aggregates": aggregates})
            conn.execute(
                text(
                    """
                    INSERT INTO data_update_runs
                      (snapshot_id,generated_at,price_date,revenue_month,status,details)
                    VALUES (:snapshot_id,:generated_at,:price_date,:revenue_month,'PASS',CAST(:details AS jsonb))
                    ON CONFLICT (snapshot_id) DO UPDATE SET status='PASS',applied_at=now(),details=EXCLUDED.details
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "generated_at": payload["generated_at"],
                    "price_date": payload["price_date"],
                    "revenue_month": payload["revenue_month"],
                    "details": json.dumps(details, ensure_ascii=False),
                },
            )
        return {"status": "applied", "snapshot_id": snapshot_id, **details}
    except Exception as exc:
        safe_error = type(exc).__name__
        try:
            with engine.begin() as conn:
                _ensure_run_table(conn)
                conn.execute(
                    text(
                        """
                        INSERT INTO data_update_runs
                          (snapshot_id,generated_at,price_date,revenue_month,status,details)
                        VALUES (:snapshot_id,:generated_at,:price_date,:revenue_month,'FAIL',CAST(:details AS jsonb))
                        ON CONFLICT (snapshot_id) DO UPDATE SET status='FAIL',applied_at=now(),details=EXCLUDED.details
                        """
                    ),
                    {
                        "snapshot_id": snapshot_id,
                        "generated_at": payload["generated_at"],
                        "price_date": payload["price_date"],
                        "revenue_month": payload["revenue_month"],
                        "details": json.dumps({**details, "error_type": safe_error}),
                    },
                )
        except Exception:
            pass
        raise SnapshotSyncError(f"snapshot apply failed: {safe_error}") from exc


def apply_snapshot_file(engine, path: Path) -> dict:
    return apply_snapshot(engine, read_snapshot(path))
