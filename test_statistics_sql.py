import unittest

from statistics_sql import heatmap_aggregate, validate_heatmap_identifiers


class HeatmapSqlTests(unittest.TestCase):
    def test_skewness_uses_raw_moments_without_nested_aggregates(self):
        expression, label = heatmap_aggregate("yoy_pct", "偏度 (分佈形狀)")

        self.assertEqual(label, "偏度")
        self.assertIn("AVG(POWER(m.yoy_pct, 3))", expression)
        self.assertNotIn("AVG(POWER((m.yoy_pct - AVG", expression)

    def test_kurtosis_uses_raw_moments_without_nested_aggregates(self):
        expression, label = heatmap_aggregate("mom_pct", "峰度 (尾部厚度)")

        self.assertEqual(label, "峰度")
        self.assertIn("AVG(POWER(m.mom_pct, 4))", expression)
        self.assertIn("STDDEV_POP(m.mom_pct)", expression)

    def test_rejects_unknown_identifiers_and_methods(self):
        with self.assertRaises(ValueError):
            validate_heatmap_identifiers("remark", "year_close")
        with self.assertRaises(ValueError):
            validate_heatmap_identifiers("yoy_pct", "year_open; DROP TABLE x")
        with self.assertRaises(ValueError):
            heatmap_aggregate("yoy_pct", "不存在")


if __name__ == "__main__":
    unittest.main()
