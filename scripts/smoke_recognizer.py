"""Probe an installed recognizer on explicit crop files, without detection."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("images", type=Path, nargs="+")
    args = parser.parse_args()
    import cv2
    from module.ocr.recognizers import create_recognizer
    config = json.loads(args.config.read_text())
    recognizer = create_recognizer(config)
    crops = [cv2.imread(str(path)) for path in args.images]
    results, elapsed = recognizer(crops)
    print(json.dumps(dict(config=config, results=results, details=recognizer.last_details,
                          elapsed_seconds=elapsed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
