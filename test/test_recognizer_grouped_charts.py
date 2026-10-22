import math
import unittest

from scripts.plot_selected_recognizers_grouped import SELECTED, bar_values, selected_records


class GroupedChartTests(unittest.TestCase):
    def test_exact_six_models_no_seq2seq(self):
        self.assertEqual(len(SELECTED), 6)
        self.assertNotIn("vietocr_original_seq2seq", {key for key, _ in SELECTED})
        self.assertIn("nom_tesseract_spell", {key for key, _ in SELECTED})
        self.assertIn("trocr_words", {key for key, _ in SELECTED})
        self.assertNotIn("ocrdoc", {key for key, _ in SELECTED})

    def test_selection_preserves_model_order_and_excludes_others(self):
        rows = [{"artifact": "cohort/" + key, "field": field, "f1": .5}
                for key, _ in reversed(SELECTED) for field in ("title", "code")]
        rows.append({"artifact": "cohort/vietocr_original_seq2seq", "field": "title", "f1": .9})
        actual = selected_records(rows, ["title", "code"])
        self.assertEqual(len(actual), 12)
        self.assertEqual([row["model"] for row in actual[::2]], [name for _, name in SELECTED])

    def test_missing_or_duplicate_field_rejected(self):
        with self.assertRaises(ValueError):
            selected_records([], ["title"])

    def test_values_follow_field_order_and_keep_missing_distinct(self):
        rows = [{"model": "a", "field": "title", "f1": None},
                {"model": "a", "field": "code", "f1": 0},
                {"model": "a", "field": "type", "f1": .85}]
        result = bar_values(rows, "a", ["type", "code", "title"], "f1")
        self.assertEqual(result[:2], [85, 0])
        self.assertTrue(math.isnan(result[2]))


if __name__ == "__main__":
    unittest.main()
