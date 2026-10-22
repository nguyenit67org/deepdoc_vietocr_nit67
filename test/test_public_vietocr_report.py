import unittest

from scripts.report_public_vietocr_ab import paired_counts


class PublicVietocrReportTests(unittest.TestCase):
    def test_three_regressions_one_fix_is_net_minus_two(self):
        old = {str(i): i < 53 for i in range(55)}
        new = dict(old)
        for i in range(3):
            new[str(i)] = False
        new["53"] = True
        result = paired_counts(old, new)
        self.assertEqual(result["baseline_correct"], 53)
        self.assertEqual(result["candidate_correct"], 51)
        self.assertEqual(result["broke_baseline_correct"], 3)
        self.assertEqual(result["corrected_baseline_errors"], 1)
        self.assertEqual(sum(result[k] for k in ("both_correct", "both_wrong", "broke_baseline_correct", "corrected_baseline_errors")), 55)

    def test_wrong_identity_rejected(self):
        with self.assertRaises(ValueError):
            paired_counts({"a": True}, {"b": True})

    def test_empty_scope_not_fabricated(self):
        result = paired_counts({}, {})
        self.assertEqual(result["documents"], 0)
        self.assertEqual(result["candidate_correct"], 0)


if __name__ == "__main__":
    unittest.main()
