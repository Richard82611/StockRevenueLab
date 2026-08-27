import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.snapshot import read_snapshot, seal_snapshot, verify_snapshot, write_snapshot
from pipeline.build_snapshot import snapshot_changed
from pipeline.sources import _parse_mops_page, fetch_tpex_prices, fetch_twse_prices


class SourceParserTests(unittest.TestCase):
    def test_parses_twse_company_rows(self):
        response = MagicMock()
        response.url = "https://twse.example"
        response.json.return_value = {
            "stat": "OK",
            "date": "20260826",
            "tables": [
                {
                    "title": "每日收盤行情",
                    "data": [
                        ["2330", "台積電", "19,467,241", "1", "1", "2375", "2425", "2375", "2415"],
                        ["006208", "ETF", "100", "1", "1", "100", "100", "100", "100"],
                    ],
                }
            ],
        }
        with patch("pipeline.sources._get", return_value=response):
            rows, _ = fetch_twse_prices(date(2026, 8, 26))
        self.assertEqual([row["symbol"] for row in rows], ["2330.TW"])
        self.assertEqual(rows[0]["volume"], 19_467_241)

    def test_parses_tpex_company_rows(self):
        response = MagicMock()
        response.url = "https://tpex.example"
        response.json.return_value = {
            "stat": "ok",
            "date": "20260826",
            "tables": [
                {
                    "title": "上櫃股票行情",
                    "data": [["8299", "群聯", "2125", "+40", "2115", "2125", "2070", "2104", "2,909,652"]],
                }
            ],
        }
        with patch("pipeline.sources._get", return_value=response):
            rows, _ = fetch_tpex_prices(date(2026, 8, 26))
        self.assertEqual(rows[0]["symbol"], "8299.TWO")
        self.assertEqual(rows[0]["close"], 2125.0)

    def test_parses_mops_rows(self):
        html = """
        <table><tr><th>公司代號</th><th>公司名稱</th><th>當月營收</th></tr>
        <tr><td>2330</td><td>台積電</td><td>467,580,548</td><td>400,000,000</td>
        <td>300,000,000</td><td>16.9</td><td>55.8</td><td>2,000,000,000</td>
        <td>1,500,000,000</td><td>33.3</td><td>-</td></tr></table>
        """
        rows = _parse_mops_page(html, "sii", "115_07")
        self.assertEqual(rows[0]["stock_id"], "2330")
        self.assertEqual(rows[0]["rev_current"], 467_580_548)


class SnapshotTests(unittest.TestCase):
    def test_round_trip_and_checksum(self):
        payload = {
            "schema_version": 1,
            "quality": {"price_rows": 1, "revenue_rows": 1},
            "prices": [{"symbol": "2330.TW"}],
            "revenues": [{"stock_id": "2330"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json.gz"
            write_snapshot(path, payload)
            loaded = read_snapshot(path)
        self.assertEqual(loaded["prices"][0]["symbol"], "2330.TW")

    def test_rejects_tampering(self):
        sealed = seal_snapshot(
            {
                "schema_version": 1,
                "quality": {"price_rows": 0, "revenue_rows": 0},
                "prices": [],
                "revenues": [],
            }
        )
        sealed["prices"].append({"symbol": "fake"})
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify_snapshot(sealed)

    def test_ignores_generated_timestamp_when_detecting_changes(self):
        payload = {
            "schema_version": 1,
            "generated_at": "2026-08-27T00:00:00+00:00",
            "quality": {"price_rows": 0, "revenue_rows": 0},
            "prices": [],
            "revenues": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json.gz"
            write_snapshot(path, payload)
            payload["generated_at"] = "2026-08-27T01:00:00+00:00"
            self.assertFalse(snapshot_changed(path, payload))


if __name__ == "__main__":
    unittest.main()
