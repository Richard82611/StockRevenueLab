import unittest

from analysis_periods import year_label


class AnalysisPeriodTests(unittest.TestCase):
    def test_marks_current_data_year_as_ytd(self):
        self.assertEqual(year_label("2026", "2026-08-26"), "2026（YTD，截至 2026-08-26）")

    def test_leaves_completed_year_plain(self):
        self.assertEqual(year_label("2025", "2026-08-26"), "2025")


if __name__ == "__main__":
    unittest.main()
