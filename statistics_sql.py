"""Validated PostgreSQL expressions used by the heatmap statistics."""

from __future__ import annotations


ALLOWED_REVENUE_METRICS = {"yoy_pct", "mom_pct"}
ALLOWED_ANNUAL_PRICE_FIELDS = {"year_close", "year_high"}


def validate_heatmap_identifiers(metric_col: str, price_field: str) -> None:
    if metric_col not in ALLOWED_REVENUE_METRICS:
        raise ValueError("不支援的營收指標")
    if price_field not in ALLOWED_ANNUAL_PRICE_FIELDS:
        raise ValueError("不支援的價格欄位")


def heatmap_aggregate(metric_col: str, stat_method: str) -> tuple[str, str]:
    """Return a legal PostgreSQL aggregate and its display label.

    Skewness and kurtosis use raw-moment identities.  This avoids illegal
    nested aggregates such as ``AVG(x - AVG(x))`` which PostgreSQL rejects.
    """

    if metric_col not in ALLOWED_REVENUE_METRICS:
        raise ValueError("不支援的營收指標")

    value = f"m.{metric_col}"
    if stat_method == "中位數 (排除極端值)":
        return f"percentile_cont(0.5) WITHIN GROUP (ORDER BY {value})", "中位數"
    if stat_method == "平均值 (含極端值)":
        return f"AVG({value})", "平均值"
    if stat_method == "標準差 (波動程度)":
        return f"STDDEV({value})", "標準差"
    if stat_method == "變異係數 (相對波動)":
        return (
            f"CASE WHEN AVG({value}) = 0 THEN 0 "
            f"ELSE STDDEV({value}) / ABS(AVG({value})) * 100 END",
            "變異係數%",
        )
    if stat_method == "偏度 (分佈形狀)":
        expression = f"""
        CASE
          WHEN COUNT({value}) < 2 THEN NULL
          WHEN STDDEV_POP({value}) = 0 THEN 0
          ELSE (
            AVG(POWER({value}, 3))
            - 3 * AVG({value}) * AVG(POWER({value}, 2))
            + 2 * POWER(AVG({value}), 3)
          ) / NULLIF(POWER(STDDEV_POP({value}), 3), 0)
        END
        """
        return expression, "偏度"
    if stat_method == "峰度 (尾部厚度)":
        expression = f"""
        CASE
          WHEN COUNT({value}) < 2 THEN NULL
          WHEN STDDEV_POP({value}) = 0 THEN 0
          ELSE (
            AVG(POWER({value}, 4))
            - 4 * AVG({value}) * AVG(POWER({value}, 3))
            + 6 * POWER(AVG({value}), 2) * AVG(POWER({value}, 2))
            - 3 * POWER(AVG({value}), 4)
          ) / NULLIF(POWER(STDDEV_POP({value}), 4), 0) - 3
        END
        """
        return expression, "峰度"
    if stat_method == "四分位距 (離散程度)":
        return (
            f"percentile_cont(0.75) WITHIN GROUP (ORDER BY {value}) - "
            f"percentile_cont(0.25) WITHIN GROUP (ORDER BY {value})",
            "四分位距",
        )
    if stat_method == "正樣本比例":
        return (
            f"SUM(CASE WHEN {value} > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*)",
            "正增長比例%",
        )
    raise ValueError(f"不支援的統計方法：{stat_method}")
