"""Data contract and rendering helpers for the company detail table."""

from __future__ import annotations

import pandas as pd


DETAIL_PERCENT_COLUMNS = (
    "年度股價實際漲幅%",
    "年增YoY平均%",
    "月增MoM平均%",
    "年增YoY波動%",
    "月增MoM波動%",
)

DETAIL_COVERAGE_COLUMNS = (
    "年增YoY有效月數",
    "月增MoM有效月數",
)


class DetailDataContractError(ValueError):
    """Raised when database results do not match the detail-table contract."""


def _coerce_numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    source = frame[column]
    converted = pd.to_numeric(source, errors="coerce")
    invalid = source.notna() & converted.isna()
    if invalid.any():
        examples = source.loc[invalid].astype(str).drop_duplicates().head(3).tolist()
        raise DetailDataContractError(
            f"欄位 {column} 含有 {int(invalid.sum())} 個非數值；範例：{examples}"
        )
    return converted.astype("float64")


def prepare_detail_results(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize SQL numeric/NULL values without inventing data."""

    required = set(DETAIL_PERCENT_COLUMNS + DETAIL_COVERAGE_COLUMNS)
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise DetailDataContractError(f"公司明細缺少必要欄位：{missing}")

    prepared = frame.copy()
    for column in DETAIL_PERCENT_COLUMNS + DETAIL_COVERAGE_COLUMNS:
        prepared[column] = _coerce_numeric_column(prepared, column)
    return prepared


def detail_missing_summary(frame: pd.DataFrame) -> tuple[int, int]:
    """Return (affected rows, missing statistic cells) for visible disclosure."""

    missing = frame.loc[:, DETAIL_PERCENT_COLUMNS].isna()
    return int(missing.any(axis=1).sum()), int(missing.sum().sum())


def style_detail_results(frame: pd.DataFrame):
    """Build a Styler that renders valid database NULLs as unavailable values."""

    formatters = {column: "{:.1f}%" for column in DETAIL_PERCENT_COLUMNS}
    formatters.update({column: "{:.0f}" for column in DETAIL_COVERAGE_COLUMNS})

    return (
        frame.style.format(formatters, na_rep="—")
        .background_gradient(cmap="RdYlGn", subset=["年度股價實際漲幅%"])
        .background_gradient(
            cmap="YlOrRd", subset=["年增YoY平均%", "月增MoM平均%"]
        )
        .background_gradient(
            cmap="Blues", subset=["年增YoY波動%", "月增MoM波動%"]
        )
    )
