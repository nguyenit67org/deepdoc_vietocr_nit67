import unittest
from types import SimpleNamespace

import numpy as np

from module.pipeline.ocr_page import PageOcrPrep, finish_ocr_page


def quad(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


OCR = SimpleNamespace(drop_score=0.5)


class FinishOcrPageTests(unittest.TestCase):
    def test_list_dt_boxes_with_exclusions(self):
        # sorted_boxes() returns a plain list; excluding one box must not crash.
        prep = PageOcrPrep(
            dt_boxes=[quad(0, 0, 100, 20), quad(0, 30, 100, 50), quad(0, 60, 100, 80)],
            prerecognized={0: ("hello", 0.9), 1: ("world", 0.8), 2: ("table junk", 0.7)},
            crop_indices=[],
            excluded_indices={2},
        )
        boxes = finish_ocr_page(prep, [], OCR)
        self.assertEqual([b["text"] for b in boxes], ["hello", "world"])

    def test_ndarray_dt_boxes_parity(self):
        prep = PageOcrPrep(
            dt_boxes=np.array(
                [quad(0, 0, 100, 20), quad(0, 30, 100, 50), quad(0, 60, 100, 80)],
                dtype=float,
            ),
            prerecognized={0: ("hello", 0.9), 1: ("world", 0.8), 2: ("table junk", 0.7)},
            crop_indices=[],
            excluded_indices={2},
        )
        boxes = finish_ocr_page(prep, [], OCR)
        self.assertEqual([b["text"] for b in boxes], ["hello", "world"])

    def test_all_excluded_returns_empty(self):
        prep = PageOcrPrep(
            dt_boxes=[quad(0, 0, 100, 20)],
            prerecognized={0: ("hello", 0.9)},
            crop_indices=[],
            excluded_indices={0},
        )
        self.assertEqual(finish_ocr_page(prep, [], OCR), [])

    def test_empty_or_none_returns_empty(self):
        for dt_boxes in (None, [], np.zeros((0, 4, 2))):
            prep = PageOcrPrep(
                dt_boxes=dt_boxes, prerecognized={}, crop_indices=[], excluded_indices=set()
            )
            self.assertEqual(finish_ocr_page(prep, [], OCR), [])


if __name__ == "__main__":
    unittest.main()
