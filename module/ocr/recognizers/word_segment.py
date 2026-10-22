"""Deterministic image-space whitespace splitting, not linguistic tokenization.

Fixed policy for the composite ablation only. No document, GT or filename rules.
Retain the full height (including Vietnamese accents); do not remove stamp ink.
"""
import hashlib
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np


class WhitespaceWordSegmenter:
    VERSION = "projection_whitespace_v1"

    def __init__(self, cache_dir, gap_height_ratio=0.18, pad_px=1):
        if gap_height_ratio <= 0 or type(pad_px) is not int or pad_px < 0:
            raise ValueError("Invalid whitespace segmentation policy")
        self.root = Path(cache_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.policy = dict(version=self.VERSION, gap_height_ratio=gap_height_ratio, pad_px=pad_px)

    def segment(self, image):
        rgb = np.asarray(image.convert("RGB"))
        key = hashlib.sha256(json.dumps(self.policy, sort_keys=True).encode() + str(rgb.shape).encode() + rgb.tobytes()).hexdigest()
        folder = self.root / key
        manifest = folder / "segments.json"
        hit = manifest.is_file()
        started = time.perf_counter()
        if hit:
            data = json.loads(manifest.read_text())
            if data["parent_rgb_sha256"] != hashlib.sha256(rgb.tobytes()).hexdigest() or data["policy"] != self.policy:
                raise ValueError("Stale word segmentation cache")
        else:
            h, w = rgb.shape[:2]
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
            occupied = np.flatnonzero(np.any(mask > 0, axis=0))
            boxes = []
            if len(occupied):
                # Interior runs only: leading/trailing blank margins aren't words.
                minimum = max(2, math.ceil(h * self.policy["gap_height_ratio"]))
                gaps = [(int(a), int(b)) for a, b in zip(occupied[:-1], occupied[1:]) if b - a - 1 >= minimum]
                cuts = [int(occupied[0])] + [(a + b) // 2 for a, b in gaps] + [int(occupied[-1]) + 1]
                for left, right in zip(cuts[:-1], cuts[1:]):
                    ink = occupied[(occupied >= left) & (occupied < right)]
                    if len(ink):
                        boxes.append([max(0, int(ink[0]) - self.policy["pad_px"]), 0,
                                      min(w, int(ink[-1]) + 1 + self.policy["pad_px"]), h])
            data = dict(policy=self.policy, parent_rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),
                        shape=list(rgb.shape), boxes=boxes, blank=not len(occupied),
                        segmentation_seconds=time.perf_counter() - started, words=[])
            folder.mkdir(parents=True, exist_ok=True)
            for index, box in enumerate(boxes):
                word = rgb[box[1]:box[3], box[0]:box[2]]
                name = f"word_{index:04d}.png"
                cv2.imwrite(str(folder / name), cv2.cvtColor(word, cv2.COLOR_RGB2BGR))
                data["words"].append(dict(index=index, box=box, png=name,
                                          rgb_sha256=hashlib.sha256(word.tobytes()).hexdigest()))
            temporary = manifest.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=2) + "\n")
            temporary.replace(manifest)
        words = [image.crop(box) for box in data["boxes"]]
        for word, record in zip(words, data["words"]):
            if hashlib.sha256(np.asarray(word).tobytes()).hexdigest() != record["rgb_sha256"]:
                raise ValueError("Word crop checksum mismatch")
        return words, dict(**data, cache_key=key, cache_hit=hit, cache_manifest=str(manifest),
                           segmentation_lookup_seconds=time.perf_counter() - started)
