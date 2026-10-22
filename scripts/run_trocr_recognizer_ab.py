"""Final composite word-segmentation ablation, after supplementary completion."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_recognizer_ab as runner


def main():
    for model in ("akaocr", "vietocr_original_seq2seq", "vietocr_original_transformer", "vietocr_dunghugging"):
        manifest = ROOT / f"ocr-collab/artifacts/recognizer_ab_additional_20261015/{model}/manifest.json"
        if not manifest.is_file() or json.loads(manifest.read_text()).get("status") != "completed":
            raise SystemExit(f"Supplementary model still incomplete: {model}")
    review = ROOT / "ocr-collab/artifacts/recognizer_ab_trocr_20261015/segmentation_review_final/review.json"
    if not review.is_file() or not json.loads(review.read_text()).get("diagnostic_run_approved"):
        raise SystemExit("Visual word segmentation smoke review is required")
    runner.MODELS = ("fastocr_words", "trocr_words")
    runner.main()


if __name__ == "__main__":
    main()
