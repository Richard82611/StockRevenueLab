import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import backfill_prices
from ci_apply_snapshot import SKIP_MESSAGE, gap_trading_days, run
from pipeline.snapshot import write_snapshot
from pipeline.sources import fetch_twse_trading_days

# Official October 2026 trading days around the 10/23 closure and the 10/26 make-up holiday.
OCT_2026 = [date(2026, 10, d) for d in (19, 20, 21, 22, 27, 28)]


def fake_month(year, month):
    return OCT_2026 if (year, month) == (2026, 10) else []


class RecordingConn:
    def __init__(self, scalar=None):
        self.calls = []
        self._scalar = scalar

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        result = MagicMock()
        result.scalar.return_value = self._scalar
        result.rowcount = 1
        return result

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RecordingEngine:
    def __init__(self, scalar=True):
        self.connections = []
        self._scalar = scalar

    def begin(self):
        conn = RecordingConn(self._scalar)
        self.connections.append(conn)
        return conn

    connect = begin


class MissingSecretTests(unittest.TestCase):
    def test_missing_or_blank_secret_skips_without_touching_database(self):
        for environ in ({}, {"DATABASE_URL": ""}, {"DATABASE_URL": "   "}):
            logs = []
            factory = MagicMock()
            code = run(Path("unused.json.gz"), environ=environ, engine_factory=factory, log=logs.append)
            self.assertEqual(code, 0)
            self.assertEqual(logs, [SKIP_MESSAGE])
            factory.assert_not_called()


class GapDayTests(unittest.TestCase):
    def test_skips_official_closures_like_1023_and_1026(self):
        gap = gap_trading_days(date(2026, 10, 21), date(2026, 10, 28), fake_month)
        self.assertEqual(gap, [date(2026, 10, 22), date(2026, 10, 27)])

    def test_no_gap_when_database_is_current(self):
        self.assertEqual(gap_trading_days(date(2026, 10, 22), date(2026, 10, 27), fake_month), [])
        self.assertEqual(gap_trading_days(date(2026, 10, 27), date(2026, 10, 27), fake_month), [])
        self.assertEqual(gap_trading_days(None, date(2026, 10, 27), fake_month), [])

    def test_gap_spans_months(self):
        def month(year, m):
            return {(2026, 9): [date(2026, 9, 29), date(2026, 9, 30)], (2026, 10): OCT_2026}.get((year, m), [])

        gap = gap_trading_days(date(2026, 9, 29), date(2026, 10, 21), month)
        self.assertEqual(gap, [date(2026, 9, 30), date(2026, 10, 19), date(2026, 10, 20)])

    def test_fmtqik_parser(self):
        response = MagicMock()
        response.json.return_value = {
            "stat": "OK",
            "data": [["115/10/22", "1"], ["115/10/27", "1"]],
        }
        with patch("pipeline.sources._get", return_value=response):
            self.assertEqual(fetch_twse_trading_days(2026, 10), [date(2026, 10, 22), date(2026, 10, 27)])


class IdempotencyTests(unittest.TestCase):
    def test_backfill_replaces_keys_then_inserts_identically_on_rerun(self):
        by_day = {"2026-10-27": [{"date": "2026-10-27", "symbol": "2330.TW", "open": 1.0, "high": 1.0,
                                  "low": 1.0, "close": 1.0, "volume": 1}]}
        statements = []
        for _ in range(2):
            engine = RecordingEngine(scalar=True)
            self.assertEqual(backfill_prices.apply_prices(engine, by_day), 1)
            statements.append([sql for sql, _ in engine.connections[0].calls])
        self.assertEqual(statements[0], statements[1])
        self.assertTrue(any(sql.startswith("DELETE FROM stock_prices") for sql in statements[0]))

    def test_backfill_rejects_duplicate_symbols(self):
        row = {"date": "2026-10-27", "symbol": "2330.TW", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
        with self.assertRaises(ValueError):
            backfill_prices.apply_prices(RecordingEngine(), {"2026-10-27": [row, dict(row)]})

    def test_run_backfills_gap_then_applies_snapshot(self):
        payload = {"schema_version": 1, "price_date": "2026-10-28", "quality": {"price_rows": 0, "revenue_rows": 0},
                   "prices": [], "revenues": []}
        row = {"symbol": "2330.TW", "date": "x", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "s.json.gz"
            write_snapshot(path, payload)
            engine = RecordingEngine(scalar=date(2026, 10, 21))
            fetched = {}

            def fetch_range(days):
                fetched["days"] = days
                return {d.isoformat(): [dict(row, date=d.isoformat())] for d in days}

            with patch("backfill_prices.apply_prices", return_value=2) as apply_prices, \
                 patch("ci_apply_snapshot.refresh_aggregates_for_days", return_value={}) as refresh, \
                 patch("snapshot_sync.apply_snapshot", return_value={"status": "applied"}) as apply_snapshot:
                code = run(path, environ={"DATABASE_URL": "postgresql://fake"}, engine_factory=lambda _: engine,
                           fetch_month=fake_month, fetch_range=fetch_range, log=lambda _: None)
        self.assertEqual(code, 0)
        self.assertEqual(fetched["days"], [date(2026, 10, 22), date(2026, 10, 27)])
        apply_prices.assert_called_once()
        refresh.assert_called_once()
        apply_snapshot.assert_called_once()


class AggregateRefreshTests(unittest.TestCase):
    def test_refreshes_each_touched_week_month_and_year_once(self):
        from ci_apply_snapshot import refresh_aggregates_for_days

        by_day = {d: [{"symbol": "2330.TW"}] for d in ("2026-10-22", "2026-10-27")}
        with patch("snapshot_sync._relation_info", return_value={}), \
             patch("snapshot_sync._refresh_aggregate", return_value=1) as refresh:
            refresh_aggregates_for_days(RecordingEngine(), by_day)
        calls = sorted((c.kwargs["table_name"], c.kwargs["cutoff"]) for c in refresh.call_args_list)
        self.assertEqual(calls, [
            ("stock_annual_k", date(2026, 10, 27)),
            ("stock_monthly_k", date(2026, 10, 27)),
            ("stock_weekly_k", date(2026, 10, 22)),
            ("stock_weekly_k", date(2026, 10, 27)),
        ])


if __name__ == "__main__":
    unittest.main()
