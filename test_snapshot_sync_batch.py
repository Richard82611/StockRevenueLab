import json
import unittest

from datetime import date

from snapshot_sync import _insert_rows, _refresh_aggregate


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))


class FakeResult:
    rowcount = 1


class AggregateConn(FakeConn):
    def execute(self, statement, params=None):
        super().execute(statement, params)
        return FakeResult()


class WeeklyMondayRuleTests(unittest.TestCase):
    def test_weekly_rows_are_dated_by_monday(self):
        conn = AggregateConn()
        relation = {"type": "table", "columns": {"date", "symbol", "w_open", "w_close", "w_high", "w_low"}}
        _refresh_aggregate(
            conn, table_name="stock_weekly_k", relation=relation, symbols=["2330.TW"], cutoff=date(2026, 10, 22)
        )
        insert_sql, params = conn.calls[-1]
        self.assertIn('CAST(:start AS date) AS "date"', insert_sql)
        self.assertNotIn("MAX(date::date)", insert_sql)
        self.assertEqual(params["start"], date(2026, 10, 19))
        self.assertEqual(params["start"].weekday(), 0)


class BatchInsertTests(unittest.TestCase):
    def test_batches_rows_with_fixed_sql_text(self):
        conn = FakeConn()
        rows = [{"symbol": f"{i:04d}.TW", "close": float(i)} for i in range(1201)]
        count = _insert_rows(conn, "stock_prices", ["symbol", "close"], rows, batch_size=500)
        self.assertEqual(count, 1201)
        self.assertEqual(len(conn.calls), 3)
        sqls = [sql for sql, _ in conn.calls]
        self.assertEqual(len(set(sqls)), 1)
        self.assertEqual(len(sqls[0]), len(sqls[2]))
        self.assertIn("json_populate_recordset", sqls[0])
        self.assertIn("CAST(:payload AS json)", sqls[0])
        self.assertNotIn(":p0_", sqls[0])
        first = json.loads(conn.calls[0][1]["payload"])
        last = json.loads(conn.calls[2][1]["payload"])
        self.assertEqual(len(first), 500)
        self.assertEqual(len(conn.calls[0][1]), 1)
        self.assertEqual(first[0]["symbol"], "0000.TW")
        self.assertEqual(last[0]["symbol"], "1000.TW")
        self.assertEqual(last[-1]["symbol"], "1200.TW")

    def test_negative_zero_matches_numeric_literal_sign(self):
        conn = FakeConn()
        _insert_rows(conn, "monthly_revenue", ["mom_pct"], [{"mom_pct": -0.0}])
        raw = conn.calls[0][1]["payload"]
        self.assertNotIn("-0.0", raw)
        self.assertEqual(json.loads(raw), [{"mom_pct": 0.0}])

    def test_nonfinite_floats_are_json_strings(self):
        conn = FakeConn()
        _insert_rows(
            conn,
            "stock_prices",
            ["close"],
            [{"close": float("nan")}, {"close": float("inf")}, {"close": float("-inf")}, {"close": None}],
        )
        raw = conn.calls[0][1]["payload"]
        self.assertNotIn("NaN", raw.replace('"NaN"', ""))
        self.assertNotIn("Infinity", raw.replace('"Infinity"', "").replace('"-Infinity"', ""))
        self.assertEqual(
            json.loads(raw),
            [{"close": "NaN"}, {"close": "Infinity"}, {"close": "-Infinity"}, {"close": None}],
        )

    def test_empty_rows_do_nothing(self):
        conn = FakeConn()
        self.assertEqual(_insert_rows(conn, "t", ["a"], []), 0)
        self.assertEqual(conn.calls, [])


class SymbolArraySqlTests(unittest.TestCase):
    def test_symbol_filter_sql_does_not_grow_with_symbol_count(self):
        relation = {
            "type": "table",
            "columns": {"date", "symbol", "w_open", "w_close", "w_high", "w_low", "w_volume"},
        }
        short = AggregateConn()
        long = AggregateConn()
        _refresh_aggregate(
            short, table_name="stock_weekly_k", relation=relation, symbols=["2330.TW"], cutoff=date(2026, 10, 22)
        )
        _refresh_aggregate(
            long,
            table_name="stock_weekly_k",
            relation=relation,
            symbols=[f"{index:04d}.TW" for index in range(1500)],
            cutoff=date(2026, 10, 22),
        )
        short_sql = [sql for sql, _ in short.calls]
        long_sql = [sql for sql, _ in long.calls]
        self.assertEqual(short_sql, long_sql)
        delete_sql, delete_params = long.calls[0]
        insert_sql, insert_params = long.calls[1]
        self.assertIn("CAST(:symbols AS text[])", delete_sql)
        self.assertIn("CAST(:symbols AS text[])", insert_sql)
        self.assertNotIn("ARRAY[", delete_sql)
        self.assertIsInstance(delete_params["symbols"], str)
        self.assertIsInstance(insert_params["symbols"], str)
        self.assertTrue(delete_params["symbols"].startswith("{"))
        self.assertEqual(len(delete_sql), len(short.calls[0][0]))
        self.assertEqual(delete_params["start"], date(2026, 10, 19))


if __name__ == "__main__":
    unittest.main()
