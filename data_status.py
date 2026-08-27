"""Read-only database freshness and schema diagnostics."""

from __future__ import annotations

from sqlalchemy import text


_TABLES = {
    "monthly_revenue": "report_month",
    "stock_prices": "date",
    "stock_weekly_k": "date",
    "stock_monthly_k": "report_month",
    "stock_annual_k": "year",
}


def read_data_status(engine) -> dict:
    """Return non-sensitive row counts, cutoffs, relation types, and columns."""
    status: dict[str, dict] = {}
    with engine.connect() as conn:
        relations = {
            row.table_name: row.relation_type
            for row in conn.execute(
                text(
                    """
                    SELECT c.relname AS table_name,
                           CASE c.relkind
                             WHEN 'r' THEN 'table'
                             WHEN 'v' THEN 'view'
                             WHEN 'm' THEN 'materialized_view'
                             ELSE c.relkind::text
                           END AS relation_type
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relname = ANY(:names)
                    """
                ),
                {"names": list(_TABLES)},
            )
        }
        columns: dict[str, list[str]] = {}
        for row in conn.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ANY(:names)
                ORDER BY table_name, ordinal_position
                """
            ),
            {"names": list(_TABLES)},
        ):
            columns.setdefault(row.table_name, []).append(row.column_name)

        for table_name, cutoff_column in _TABLES.items():
            if table_name not in relations:
                status[table_name] = {"exists": False}
                continue
            row = conn.execute(
                text(
                    f'SELECT COUNT(*)::bigint AS rows, '
                    f'MIN("{cutoff_column}")::text AS min_value, '
                    f'MAX("{cutoff_column}")::text AS max_value '
                    f'FROM "{table_name}"'
                )
            ).one()
            status[table_name] = {
                "exists": True,
                "relation_type": relations[table_name],
                "columns": columns.get(table_name, []),
                "rows": row.rows,
                "min_value": row.min_value,
                "max_value": row.max_value,
            }
    return status
