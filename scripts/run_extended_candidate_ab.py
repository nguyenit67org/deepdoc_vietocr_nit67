"""Guarded second cohort: VNHTR no-head checkpoints and EasyOCR pretrained."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_recognizer_ab as runner


if __name__ == "__main__":
    runner.MODELS = ("vnhtr_vgg_base", "vnhtr_trocr_base", "easyocr_latin_pretrained")
    runner.main()
