"""Shared latest-period selection for all analysis pages."""

from __future__ import annotations

from sqlalchemy import text


def available_analysis_years(engine) -> list[str]:
    with engine.connect() as conn:
        years = [
            str(row.year)
            for row in conn.execute(
                text(
                    """
                    SELECT DISTINCT year::text AS year
                    FROM stock_annual_k
                    WHERE year::text ~ '^\\d{4}$'
                    ORDER BY year::text DESC
                    """
                )
            )
        ]
    return years or ["2026"]


def year_label(year: str, latest_price_date: str | None) -> str:
    if latest_price_date and year == latest_price_date[:4]:
        return f"{year}（YTD，截至 {latest_price_date}）"
    return year
