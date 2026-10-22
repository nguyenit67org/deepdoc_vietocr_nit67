"""Run the pinned candidate cohort through the existing guarded AB harness."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_recognizer_ab as runner


if __name__ == "__main__":
    runner.MODELS = ("trocr_duyle", "vnhtr_vgg", "vnhtr_trocr", "vietdoc_vudang_pth")
    runner.main()
