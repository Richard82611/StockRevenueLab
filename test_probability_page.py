"""pages/probability.py 的純函式與 SQL 契約測試（不連資料庫）。

頁面在 import 時就會執行 Streamlit UI，所以這裡只用 ast 取出函式定義，
在注入 mock 的命名空間中執行，資料庫一律以 mock 取代。
"""

import ast
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "pages/probability.py"
FUNCTIONS = ("fetch_multi_year_data", "fetch_prob_data", "fetch_prob_data_alt", "calculate_expected_value")


def _passthrough_cache(*args, **kwargs):
    if args and callable(args[0]) and not kwargs:
        return args[0]
    return lambda func: func


def load_page_functions(engine=None):
    tree = ast.parse(PAGE.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in FUNCTIONS]
    module = ast.Module(body=nodes, type_ignores=[])
    st = mock.MagicMock()
    st.cache_data = _passthrough_cache
    namespace = {
        "st": st,
        "pd": pd,
        "np": np,
        "text": lambda sql: sql,
        "get_engine": mock.MagicMock(return_value=engine or mock.MagicMock()),
    }
    exec(compile(module, str(PAGE), "exec"), namespace)
    return namespace


def stats_row(hits, count, avg, median, win, double=0.0, std=10.0):
    return {
        "爆發次數": hits, "股票檔數": count, "平均年度漲幅%": avg, "中位數漲幅%": median,
        "勝率(>20%)": win, "翻倍率(>100%)": double, "最低漲幅%": -5.0, "最高漲幅%": 50.0, "標準差%": std,
    }


class CalculateExpectedValueTests(unittest.TestCase):
    def setUp(self):
        self.calc = load_page_functions()["calculate_expected_value"]

    def test_empty_frame_returns_empty(self):
        self.assertTrue(self.calc(pd.DataFrame()).empty)

    def test_scores_follow_documented_formulas(self):
        row = self.calc(pd.DataFrame([stats_row(3, 10, 30.0, 20.0, 50.0, std=15.0)])).iloc[0]
        self.assertEqual(row["期望值分數"], 3.0)          # 30*10/100
        self.assertEqual(row["風險調整分數"], 2.0)        # 30/15
        self.assertEqual(row["成功率分數"], 15.0)         # 30*0.5
        self.assertEqual(row["平均-中位差"], 10.0)
        self.assertEqual(row["綜合評分"], round((3.0 + 2.0 + 15.0) / 3, 2))

    def test_std_below_one_is_floored_to_one(self):
        row = self.calc(pd.DataFrame([stats_row(1, 2, 8.0, 8.0, 0.0, std=0.2)])).iloc[0]
        self.assertEqual(row["風險調整分數"], 8.0)

    def test_zero_average_gives_zero_expected_and_composite(self):
        row = self.calc(pd.DataFrame([stats_row(1, 5, 0.0, 0.0, 0.0)])).iloc[0]
        self.assertEqual(row["期望值分數"], 0)
        self.assertEqual(row["綜合評分"], 0)

    def test_preserves_row_order_and_count(self):
        df = pd.DataFrame([stats_row(5, 1, 10.0, 9.0, 100.0), stats_row(2, 4, -5.0, -6.0, 0.0)])
        out = self.calc(df)
        self.assertEqual(list(out["爆發次數"]), [5, 2])
        self.assertEqual(list(out["股票檔數"]), [1, 4])


class FetchProbDataAltTests(unittest.TestCase):
    def run_alt(self, raw):
        ns = load_page_functions()
        with mock.patch.object(pd, "read_sql_query", return_value=raw) as read_sql:
            out = ns["fetch_prob_data_alt"](2024, "yoy_pct", 100, 1000)
        return out, read_sql.call_args[0][0]

    def test_empty_raw_returns_empty(self):
        out, _ = self.run_alt(pd.DataFrame(columns=["hits", "ret"]))
        self.assertTrue(out.empty)

    def test_python_statistics_per_hit_group(self):
        raw = pd.DataFrame({"hits": [2, 2, 2, 5], "ret": [10.0, 30.0, 150.0, -4.0]})
        out, _ = self.run_alt(raw)
        self.assertEqual(list(out["爆發次數"]), [5, 2])  # 依爆發次數遞減
        two = out[out["爆發次數"] == 2].iloc[0]
        self.assertEqual(two["股票檔數"], 3)
        self.assertEqual(two["平均年度漲幅%"], 63.3)
        self.assertEqual(two["中位數漲幅%"], 30.0)
        self.assertEqual(two["勝率(>20%)"], 66.7)
        self.assertEqual(two["翻倍率(>100%)"], 33.3)
        self.assertEqual(two["最低漲幅%"], 10.0)
        self.assertEqual(two["最高漲幅%"], 150.0)

    def test_single_stock_group_has_zero_std(self):
        out, _ = self.run_alt(pd.DataFrame({"hits": [1], "ret": [12.0]}))
        self.assertEqual(out.iloc[0]["標準差%"], 0)

    def test_sql_uses_minguo_window_dec_to_nov(self):
        _, sql = self.run_alt(pd.DataFrame(columns=["hits", "ret"]))
        self.assertIn("report_month = '112_12'", sql)   # 2024 → 民國 113，前一年 12 月
        self.assertIn("LIKE '113_%'", sql)
        self.assertIn("report_month <= '113_11'", sql)
        self.assertIn("yoy_pct >= 100 AND yoy_pct < 1000", sql)
        self.assertIn("WHERE year = '2024'", sql)


class FetchProbDataTests(unittest.TestCase):
    def test_price_field_is_used_in_return_formula(self):
        ns = load_page_functions()
        with mock.patch.object(pd, "read_sql_query", return_value=pd.DataFrame()) as read_sql:
            ns["fetch_prob_data"](2023, "mom_pct", 0, 20, "year_high")
        sql = read_sql.call_args[0][0]
        self.assertIn("((year_high - year_open) / year_open)*100", sql)
        self.assertIn("PERCENTILE_CONT(0.5)", sql)
        self.assertIn("ORDER BY hits DESC", sql)

    def test_falls_back_to_alt_query_on_error(self):
        ns = load_page_functions()
        raw = pd.DataFrame({"hits": [1, 1], "ret": [5.0, 25.0]})
        with mock.patch.object(pd, "read_sql_query", side_effect=[RuntimeError("no percentile"), raw]):
            out = ns["fetch_prob_data"](2023, "yoy_pct", 50, 100)
        self.assertEqual(out.iloc[0]["中位數漲幅%"], 15.0)
        ns["st"].error.assert_called_once()
        ns["st"].warning.assert_called_once()


class FetchMultiYearDataTests(unittest.TestCase):
    def test_empty_stock_list_skips_database(self):
        ns = load_page_functions()
        self.assertTrue(ns["fetch_multi_year_data"]([], 2024).empty)
        ns["get_engine"].assert_not_called()

    def test_year_window_and_ids(self):
        ns = load_page_functions()
        with mock.patch.object(pd, "read_sql_query", return_value=pd.DataFrame()) as read_sql:
            ns["fetch_multi_year_data"](["2330", "2317"], "2024")
        sql = read_sql.call_args[0][0]
        self.assertIn("IN ('2330','2317')", sql)
        self.assertIn("BETWEEN 2022 AND 2025", sql)


class ProbabilityPageSourceContractTests(unittest.TestCase):
    def setUp(self):
        self.source = PAGE.read_text(encoding="utf-8")

    def test_page_compiles(self):
        compile(self.source, str(PAGE), "exec")

    def test_expected_functions_exist(self):
        names = {n.name for n in ast.parse(self.source).body if isinstance(n, ast.FunctionDef)}
        for name in FUNCTIONS + ("get_period_context",):
            self.assertIn(name, names)

    def test_metric_and_price_choices_are_whitelisted(self):
        self.assertIn('["yoy_pct", "mom_pct"]', self.source)
        self.assertIn('price_field = "year_close"', self.source)
        self.assertIn('price_field = "year_high"', self.source)

    def test_uses_shared_db_connection(self):
        self.assertIn("from db_connection import get_engine", self.source)
        self.assertNotIn("create_engine(", self.source)


if __name__ == "__main__":
    unittest.main()
