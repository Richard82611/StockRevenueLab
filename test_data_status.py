import unittest
from unittest.mock import MagicMock

from data_status import read_data_status


class DataStatusTests(unittest.TestCase):
    def test_reads_cutoffs_without_row_contents(self):
        engine = MagicMock()
        conn = engine.connect.return_value.__enter__.return_value
        conn.execute.side_effect = [
            [
                MagicMock(table_name="stock_prices", relation_type="table"),
                MagicMock(table_name="monthly_revenue", relation_type="table"),
            ],
            [
                MagicMock(table_name="monthly_revenue", column_name="report_month"),
                MagicMock(table_name="stock_prices", column_name="date"),
            ],
            MagicMock(one=lambda: MagicMock(rows=10, min_value="115_01", max_value="115_07")),
            MagicMock(one=lambda: MagicMock(rows=20, min_value="2026-01-02", max_value="2026-08-26")),
        ]

        status = read_data_status(engine)

        self.assertEqual(status["monthly_revenue"]["max_value"], "115_07")
        self.assertEqual(status["stock_prices"]["max_value"], "2026-08-26")
        self.assertFalse(status["stock_weekly_k"]["exists"])


if __name__ == "__main__":
    unittest.main()
