import unittest

from scripts.analyze_trocr_saved_errors import geometry_flags, select_cases


class TrocrErrorAnalysisTests(unittest.TestCase):
    def test_geometry_flags_are_explicit_not_accuracy(self):
        flags = geometry_flags([20, 200, 3], [[0, 0, 200, 20]])
        self.assertTrue(flags["single_wide_segment"])
        self.assertEqual(flags["wide_segments"], 1)
        self.assertFalse(flags["vertical_parent"])
        self.assertNotIn("error", flags)

    def test_blank_geometry(self):
        flags = geometry_flags([20, 200, 3], [])
        self.assertEqual(flags["segments"], 0)
        self.assertEqual(flags["max_segment_aspect"], 0)
        self.assertFalse(flags["single_wide_segment"])

    def test_vertical_and_narrow_flags(self):
        flags = geometry_flags([100, 20, 3], [[0, 0, 10, 100], [11, 0, 20, 100]])
        self.assertTrue(flags["vertical_parent"])
        self.assertEqual(flags["narrow_segments"], 2)

    def test_selection_is_reproducible_unique_and_capped(self):
        rows = [dict(document_id=f"doc_{i//3}", page_index_0based=0, crop_index=i,
            segments=3, parent_aspect_ratio=4, vertical_parent=False, wide_segments=0,
            narrow_segments=0, max_segment_aspect=2, single_wide_segment=False,
            blank=False, trocr_text="a", fastocr_word_text="b", fastocr_line_text="b") for i in range(90)]
        result = select_cases(rows)
        self.assertEqual(result, select_cases(rows))
        self.assertEqual(len(result), 30)
        self.assertEqual(len({row["case_id"] for row in result}), 30)
        self.assertEqual(len({(row["document_id"],row["crop_index"]) for row in result}), 30)
        self.assertTrue(all(sum(other["document_id"] == row["document_id"] for other in result) <= 3 for row in result))


if __name__ == "__main__":
    unittest.main()
