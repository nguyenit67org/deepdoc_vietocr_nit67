"""Adapter for pinned upstream HTR-ConvText VNOnDB sources/checkpoint.

    License clarification pending: keep upstream sources/weights out of shared
    distributions; this adapter is used for the approved internal benchmark.
"""
import argparse
import ast
import hashlib
import importlib.util
from pathlib import Path
import sys
import types

import numpy as np

from .base import BatchedRecognizer, RecognitionResult
from .onnx_utils import ctc_decode


def load_upstream(root):
    """Namespace upstream's generic `model` package; do not pollute sys.path.

    Only compatibility edit in memory: absolute `from model import resnet18`
    becomes a relative import. Downloaded source files remain unchanged.
    """
    namespace = "_deepdoc_htr_" + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]
    if namespace + ".htr_convtext" in sys.modules:
        return sys.modules[namespace + ".htr_convtext"]
    package = types.ModuleType(namespace)
    package.__path__ = [str(root / "model")]
    sys.modules[namespace] = package
    path = root / "model/htr_convtext.py"
    source = path.read_text()
    if source.count("from model import resnet18") != 1:
        raise ValueError("Unsupported upstream HTR import layout")
    source = source.replace("from model import resnet18", "from . import resnet18")
    name = namespace + ".htr_convtext"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def vnondb_alphabet(path):
    # Read the pinned upstream vocabulary as data without importing its dataset,
    # which otherwise imports generic `utils` and augmentation packages.
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            if any(isinstance(v, ast.Constant) and v.value == "vnondb" for v in node.test.comparators):
                strings = [v.value for statement in node.body for v in ast.walk(statement)
                           if isinstance(v, ast.Constant) and isinstance(v.value, str) and len(v.value) > 100]
                if len(strings) == 1:
                    return strings[0]
    raise ValueError("Missing unambiguous upstream VNOnDB alphabet")


class HtrConvTextRecognizer(BatchedRecognizer):
    def __init__(self, model_dir, device_id=0, device="cuda", max_batch_size=16):
        super().__init__(max_batch_size)
        import torch
        root = Path(model_dir)
        self.device = torch.device(f"cuda:{device_id}" if device == "cuda" else device)
        self.vocab = ["blank", *vnondb_alphabet(root / "data/dataset.py")]
        upstream = load_upstream(root)
        self.model = upstream.create_model(nb_cls=len(self.vocab), img_size=[64, 512])
        from numpy._core.multiarray import _reconstruct
        with torch.serialization.safe_globals([argparse.Namespace, _reconstruct, np.ndarray, np.dtype,
                                                type(np.dtype("float64")), type(np.dtype("float32")),
                                                type(np.dtype("int64")), type(np.dtype("uint32"))]):
            checkpoint = torch.load(root / "checkpoints/hands-vnondb.pth", map_location="cpu", weights_only=True)
        state = {key.removeprefix("module."): value for key, value in checkpoint["state_dict_ema"].items()}
        self.model.load_state_dict(state, strict=True)
        self.model = self.model.to(self.device).eval()

    @staticmethod
    def preprocess(image):
        gray = image.convert("L")
        width = max(1, min(int(gray.width * 64 / gray.height), 512))
        array = np.asarray(gray.resize((width, 64)), dtype=np.float32) / 255.0
        return np.pad(array, ((0, 0), (0, 512 - width)), constant_values=1.0)[None]

    def _recognize_batch(self, images):
        import torch
        batch = torch.from_numpy(np.stack([self.preprocess(image) for image in images])).to(self.device)
        with torch.inference_mode():
            probabilities = self.model(batch).softmax(-1).cpu().numpy()
        return [RecognitionResult(text, score, metadata={"resize": "grayscale height64, maxwidth512, white right-pad", "decoder": "CTC greedy"})
                for text, score in ctc_decode(probabilities, self.vocab)]
