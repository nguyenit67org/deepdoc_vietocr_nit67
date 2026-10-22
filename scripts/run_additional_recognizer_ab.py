"""Supplementary cohort runner, activated only after primary GPU runs complete."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_recognizer_ab as runner

MODELS = ("akaocr", "vietocr_original_seq2seq", "vietocr_original_transformer", "vietocr_dunghugging")


def main():
    import json
    primary = ROOT / "ocr-collab/artifacts/recognizer_ab_20261015/senocr/manifest.json"
    if not primary.is_file() or json.loads(primary.read_text()).get("status") != "completed":
        raise SystemExit("Primary SenOCR still incomplete: preparation/CPU smoke only; do not compete for GPU")
    from module.ocr.recognizers import available_recognizers
    if not {"akaocr", "vietocr_original"}.issubset(available_recognizers()):
        raise SystemExit("Supplementary adapters are staged but not registered. Activate registry after primary completion, then run a fresh FastOCR control first.")
    runner.MODELS = MODELS
    runner.main()


if __name__ == "__main__":
    main()
