"""Streamlit-safe dataframe presentation helpers.

Pandas ``Styler`` formatting is HTML-oriented.  ``st.dataframe`` serializes the
underlying values through Arrow, so ``Styler.format(na_rep=...)`` is not a
reliable way to control what users see for database NULLs.  These helpers build
the actual presentation dataframe before it reaches Streamlit.
"""

from __future__ import annotations

from collections.abc import Mapping
import math

import pandas as pd


class TableDisplayContractError(ValueError):
    """Raised when a column declared numeric contains an unexpected value."""


def _format_number(value: float, template: str, missing: str, infinity: str) -> str:
    if pd.isna(value):
        return missing
    number = float(value)
    if not math.isfinite(number):
        return infinity if number > 0 else f"-{infinity}"
    return template.format(number)


def streamlit_display_frame(
    frame: pd.DataFrame,
    formats: Mapping[str, str] | None = None,
    *,
    missing: str = "—",
    infinity: str = "∞",
) -> pd.DataFrame:
    """Return values exactly as they should appear in ``st.dataframe``.

    Declared numeric columns are validated before formatting.  All remaining
    database NULL/NaN values are replaced as well, so Arrow never receives a
    display-layer ``None`` that could become a black cell or the text ``None``.
    The source dataframe is never mutated.
    """

    display = frame.copy().astype(object)
    formats = formats or {}

    unknown = sorted(set(formats).difference(display.columns))
    if unknown:
        raise TableDisplayContractError(f"格式指定了不存在的欄位：{unknown}")

    for column, template in formats.items():
        source = display[column]
        numeric = pd.to_numeric(source, errors="coerce")
        invalid = source.notna() & numeric.isna()
        if invalid.any():
            examples = source.loc[invalid].astype(str).drop_duplicates().head(3).tolist()
            raise TableDisplayContractError(
                f"欄位 {column} 含有 {int(invalid.sum())} 個非數值；範例：{examples}"
            )
        display[column] = numeric.map(
            lambda value: _format_number(value, template, missing, infinity)
        )

    for column in display.columns:
        if column in formats:
            continue
        display[column] = display[column].map(
            lambda value: missing if pd.isna(value) else value
        )

    return display


def numeric_column_formats(
    frame: pd.DataFrame,
    template: str,
    *,
    exclude: tuple[str, ...] = (),
) -> dict[str, str]:
    """Build one format mapping for all numeric columns in a dataframe."""

    excluded = set(exclude)
    return {
        column: template
        for column in frame.select_dtypes(include="number").columns
        if column not in excluded
    }
