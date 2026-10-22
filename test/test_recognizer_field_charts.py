import unittest

from scripts.plot_recognizer_field_metrics import metric_number, RUNS, TITLES


class FieldChartTests(unittest.TestCase):
    def test_missing_metric_is_not_zero(self):
        self.assertIsNone(metric_number(""))
        self.assertIsNone(metric_number(None))
        self.assertEqual(metric_number("0"), 0.0)

    def test_ratio_scale(self):
        self.assertEqual(metric_number("0.85"), .85)
        self.assertEqual(metric_number("1"), 1.0)

    def test_invalid_metrics_rejected(self):
        for value in ("nan", "inf", "-0.1", "85"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                metric_number(value)

    def test_chart_scope_and_baseline_uniqueness(self):
        self.assertEqual(len(TITLES), 12)
        self.assertNotIn("receiverDate", TITLES)
        self.assertEqual(len(RUNS), 13)
        self.assertEqual(len({path for _, path in RUNS}), 13)
        self.assertEqual(sum(path.endswith("/fastocr_control") for _, path in RUNS), 1)


if __name__ == "__main__":
    unittest.main()
