import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PIL import Image

from module.ocr.recognizers.base import BatchedRecognizer
from module.ocr.recognizers.pytesseract_direct import PytesseractDirectRecognizer,validate_options
from scripts.run_pytesseract_selected_pages import selected_only_pages,verify_selected_evidence


class SelectedPagesTests(unittest.TestCase):
    def test_never_fill_unselected_pages_and_preserve_indices(self):
        pages=selected_only_pages(20,{1:[{"content":"header"}],17:[{"content":"signer"}]})
        self.assertEqual(len(pages),20)
        self.assertEqual([i for i,p in enumerate(pages) if p],[1,17])
        self.assertIsNot(pages[0],pages[2])

    def test_invalid_page_rejected(self):
        with self.assertRaises(ValueError):
            selected_only_pages(2,{2:[]})

    def test_evidence_from_unselected_page_is_rejected(self):
        verify_selected_evidence({"code":[{"page":2}],"type":[]},[1,17])
        with self.assertRaises(ValueError):
            verify_selected_evidence({"code":[{"page":5}]},[1,17])

    def test_language_psm_engine_are_explicit(self):
        for psm in [6,7,13]:
            validate_options("vie",psm,1,10,4)
        for lang in ["vi","vn"]:
            with self.assertRaises(ValueError):
                validate_options(lang,7,1,10,4)
        with self.assertRaises(ValueError):
            validate_options("vie",7,3,10,4)


class DirectPytesseractTests(unittest.TestCase):
    def reader(self,folder,psm=7):
        r=PytesseractDirectRecognizer.__new__(PytesseractDirectRecognizer)
        BatchedRecognizer.__init__(r,32)
        r.cache=Path(folder);r.lang="vie";r.border=10;r.workers=4;r.timeout=60
        r.policy=dict(psm=psm,lang="vie",post_correct=False)
        r.config=f"--oem 1 --psm {psm}"
        r.api=SimpleNamespace(image_to_string=Mock(return_value="ngày8\n"))
        return r

    def test_no_correction_neutral_score_border_and_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            r=self.reader(folder);image=Image.new("RGB",(40,20),"white")
            output,_=r([image])
            self.assertEqual(output,[("ngày8",1.0)])
            self.assertEqual(r.api.image_to_string.call_args.args[0].size,(60,40))
            self.assertEqual(r.api.image_to_string.call_args.kwargs["lang"],"vie")
            self.assertFalse(r.last_details[0]["metadata"]["post_correct"])
            r([image]);self.assertEqual(r.api.image_to_string.call_count,1)
            self.assertTrue(r.last_details[0]["metadata"]["raw_cache_hit"])

    def test_psm_separates_cache_and_duplicates_do_not_race(self):
        with tempfile.TemporaryDirectory() as folder:
            image=Image.new("RGB",(40,20),"white");r=self.reader(folder)
            output,_=r([image,image])
            self.assertEqual(len(output),2);self.assertEqual(r.api.image_to_string.call_count,1)
            other=self.reader(folder,13);other([image]);other.api.image_to_string.assert_called_once()

    def test_corrupt_cache_does_not_trigger_silent_ocr(self):
        with tempfile.TemporaryDirectory() as folder:
            image=Image.new("RGB",(40,20),"white");r=self.reader(folder);r([image])
            path=next(Path(folder).glob("*.json"));record=json.loads(path.read_text());record["raw_text"]="changed";path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                r([image])
            self.assertEqual(r.api.image_to_string.call_count,1)


if __name__=="__main__":
    unittest.main()
