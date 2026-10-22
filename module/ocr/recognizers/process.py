"""Persistent local worker for backends with conflicting optional dependencies."""
from dataclasses import fields
import atexit
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile

import cv2
import numpy as np

from .base import BatchedRecognizer, RecognitionResult


class ProcessRecognizer(BatchedRecognizer):
    def __init__(self, config, runtime, device_id):
        super().__init__(max_batch_size=runtime.get("ipc_batch_size", 32))
        self.timeout = runtime.get("timeout_seconds", 900)
        self._stderr = tempfile.TemporaryFile(mode="w+t")
        env = os.environ.copy()
        env.update({str(key): str(value) for key, value in runtime.get("env", {}).items()})
        root = Path(__file__).resolve().parents[3]
        extra = [str(Path(p).resolve()) for p in runtime.get("pythonpath", [])]
        env["PYTHONPATH"] = os.pathsep.join([*extra, str(root), env.get("PYTHONPATH", "")])
        self._process = subprocess.Popen([runtime.get("python", sys.executable), "-m", "module.ocr.recognizers.worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr, text=True, env=env, cwd=root)
        atexit.register(self.close)
        try:
            ready = self._request(dict(config=config, device_id=device_id))
            self.has_native_confidence = ready["has_native_confidence"]
            self.worker_runtime = ready["runtime"]
        except BaseException:
            self.close()
            raise

    def _request(self, payload):
        self._process.stdin.write(json.dumps(payload) + "\n")
        self._process.stdin.flush()
        readable, _, _ = select.select([self._process.stdout], [], [], self.timeout)
        if not readable:
            self.close()
            raise TimeoutError("Recognizer worker timed out; no silent fallback")
        line = self._process.stdout.readline()
        if not line:
            self._stderr.seek(0)
            raise RuntimeError("Recognizer worker exited: " + self._stderr.read()[-12000:])
        response = json.loads(line)
        if "error" in response:
            raise RuntimeError("Recognizer worker failed: " + response["error"])
        return response

    def _recognize_batch(self, images):
        with tempfile.TemporaryDirectory(prefix="recognizer-ipc-", dir="/tmp/opencode") as folder:
            paths = []
            for index, image in enumerate(images):
                path = Path(folder) / f"{index}.png"
                if not cv2.imwrite(str(path), cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)):
                    raise OSError(f"Cannot write IPC crop: {path}")
                paths.append(str(path))
            response = self._request(dict(images=paths))
        names = {field.name for field in fields(RecognitionResult)}
        return [RecognitionResult(**{k: v for k, v in detail.items() if k in names}) for detail in response["details"]]

    def close(self):
        process = getattr(self, "_process", None)
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for handle in (process.stdin, process.stdout):
                if handle:
                    handle.close()
        log = getattr(self, "_stderr", None)
        if log is not None:
            log.close()
        atexit.unregister(self.close)

    def __del__(self):
        self.close()
