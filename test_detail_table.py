import unittest
from decimal import Decimal

import pandas as pd

from detail_table import (
    DetailDataContractError,
    detail_missing_summary,
    display_detail_results,
    prepare_detail_results,
)


def detail_frame(**overrides):
    values = {
        "代號": ["2330", "9999"],
        "名稱": ["台積電", "資料不足公司"],
        "年度股價實際漲幅%": [Decimal("12.3"), Decimal("-4.5")],
        "年增YoY平均%": [Decimal("20.0"), None],
        "月增MoM平均%": [Decimal("2.0"), Decimal("1.0")],
        "年增YoY波動%": [Decimal("8.0"), None],
        "月增MoM波動%": [Decimal("5.0"), Decimal("3.0")],
        "年增YoY有效月數": [12, 0],
        "月增MoM有效月數": [12, 1],
        "最新營收備註": ["", ""],
    }
    values.update(overrides)
    return pd.DataFrame(values)


class DetailTableContractTests(unittest.TestCase):
    def test_normalizes_decimal_values_and_preserves_database_nulls(self):
        prepared = prepare_detail_results(detail_frame())

        self.assertTrue(
            all(prepared[column].dtype == "float64" for column in prepared.columns[2:9])
        )
        self.assertTrue(pd.isna(prepared.loc[1, "年增YoY平均%"]))
        self.assertEqual(detail_missing_summary(prepared), (1, 2))

    def test_rejects_non_numeric_database_values(self):
        frame = detail_frame(**{"月增MoM平均%": [Decimal("2.0"), "壞資料"]})

        with self.assertRaisesRegex(DetailDataContractError, "月增MoM平均%"):
            prepare_detail_results(frame)

    def test_rejects_schema_drift(self):
        frame = detail_frame().drop(columns=["年增YoY有效月數"])

        with self.assertRaisesRegex(DetailDataContractError, "缺少必要欄位"):
            prepare_detail_results(frame)

    def test_streamlit_payload_contains_no_null_or_none_text(self):
        prepared = prepare_detail_results(detail_frame())

        display = display_detail_results(prepared)

        self.assertEqual(display.loc[1, "年增YoY平均%"], "—")
        self.assertEqual(display.loc[1, "年增YoY波動%"], "—")
        self.assertEqual(display.loc[0, "年度股價實際漲幅%"], "12.3%")
        self.assertFalse(display.isna().any().any())
        self.assertFalse((display.astype(str) == "None").to_numpy().any())


if __name__ == "__main__":
    unittest.main()
