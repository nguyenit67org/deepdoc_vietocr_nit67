"""Private JSONL IPC entry point. Crop-only local inference, never network APIs."""
import contextlib
import importlib.metadata
import json
import sys
import traceback


def send(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    try:
        payload = json.loads(sys.stdin.readline())
        with contextlib.redirect_stdout(sys.stderr):
            import cv2
            from . import create_recognizer
            recognizer = create_recognizer(payload["config"], payload["device_id"])
        runtime = {}
        for name in ("torch", "transformers", "huggingface-hub", "tokenizers", "numpy"):
            try:
                runtime[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                pass
        send(dict(ready=True, has_native_confidence=recognizer.has_native_confidence, runtime=runtime))
        for line in sys.stdin:
            payload = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                crops = [cv2.imread(path) for path in payload["images"]]
                recognizer(crops)
            send(dict(details=recognizer.last_details))
    except Exception:
        send(dict(error=traceback.format_exc()))


if __name__ == "__main__":
    main()
