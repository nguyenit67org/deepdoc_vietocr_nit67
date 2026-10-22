"""Strict checkpoint loading, native nhay CPU parity, and functional GPU crop smoke."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_cached_ocr_equivalence import dump, sha256
from scripts.smoke_candidate_recognizers import samples


def cpu_probe(folder, implementation, output):
    import torch
    import yaml
    from PIL import Image
    from module.ocr.recognizers.source_utils import source_package
    torch.set_num_threads(2)
    config = yaml.safe_load((folder / "config.yml").read_text())
    config["device"] = "cpu"
    config["cnn"]["pretrained"] = False
    source_package(folder / ("native_source" if implementation == "native" else "source"), "vietocr")
    if implementation == "native":
        import torchvision.models
        from vietocr.model.transformerocr import VietOCR
        from vietocr.model.vocab import Vocab
        translate = importlib.import_module("vietocr.translate")
        vocab = Vocab(config["vocab"])
        original = torchvision.models.vgg19_bn
        # Native demo hardcodes weights=DEFAULT. The OCR state supplies every
        # tensor, so intercept initialization only; never download ImageNet.
        with patch("torchvision.models.vgg19_bn", side_effect=lambda **kw: original(**{**kw, "weights": None})):
            model = VietOCR(len(vocab), config["backbone"], config["cnn"], config["transformer"], config["seq_modeling"])
    else:
        translate = importlib.import_module("vietocr.tool.translate")
        model, vocab = translate.build_model(config)
    weights = torch.load(folder / "weights.pth", map_location="cpu", weights_only=True)
    if not isinstance(weights, dict) or not all(isinstance(k, str) and torch.is_tensor(v) for k, v in weights.items()):
        raise ValueError("Expected plain tensor state_dict; no unsafe deserialization or key remapping")
    model.load_state_dict(weights, strict=True)
    if not all(torch.isfinite(value).all().item() for value in weights.values()):
        raise ValueError("Nonfinite checkpoint tensors")
    model.eval()
    chosen = list(samples())
    outputs = []
    for index in (0, 4, len(chosen) - 1):
        _, meta = chosen[index]
        with Image.open(meta["path"]) as image:
            image = image.convert("RGB")
            tensor = translate.process_input(image, config["dataset"]["image_height"],
                config["dataset"]["image_min_width"], config["dataset"]["image_max_width"])
        with torch.inference_mode():
            result = translate.translate(tensor, model, max_seq_length=128)
        tokens = (result if implementation == "native" else result[0])[0].tolist()
        outputs.append(dict(sample=meta, tensor_sha256=hashlib.sha256(tensor.numpy().tobytes()).hexdigest(),
            tensor_shape=list(tensor.shape), tokens=tokens, text=vocab.decode(tokens)))
    dump(output, dict(status="passed", implementation=implementation, tensor_count=len(weights),
        parameter_elements=sum(v.numel() for v in weights.values()), strict_state_dict=True, finite_tensors=True,
        outputs=outputs, native_initialization_override="ImageNet weights=None only; full OCR state loaded strictly" if implementation == "native" else None))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--implementation", choices=("native", "upstream"))
    args = parser.parse_args()
    config = json.loads((ROOT / f"conf/recognizers/{args.model}.json").read_text())
    folder = ROOT / config["model_dir"]
    if args.implementation:
        return cpu_probe(folder, args.implementation, args.output)
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((folder / "download_manifest.json").read_text())
    for rel, info in manifest["artifacts"].items():
        if sha256(folder / rel) != info["sha256"]:
            raise ValueError(f"Staged asset changed: {rel}")
    for implementation in (("upstream", "native") if args.model == "vietocr_nhay_seq2seq" else ("upstream",)):
        subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), str(args.output / f"{implementation}_cpu.json"),
            "--model", args.model, "--implementation", implementation], cwd=ROOT, check=True)
    if args.model == "vietocr_nhay_seq2seq":
        upstream = json.loads((args.output / "upstream_cpu.json").read_text())
        native = json.loads((args.output / "native_cpu.json").read_text())
        if upstream["outputs"] != native["outputs"]:
            raise ValueError("Native vs upstream CPU token/preprocessing mismatch; do not substitute implementations silently")
        dump(args.output / "native_parity.json", dict(status="passed", compared_crops=len(native["outputs"]),
            exact_input_tensors=True, exact_token_ids=True, exact_texts=True,
            limit="Three fixed smoke crops, not full-corpus or CPU/GPU numerical equivalence"))
    from module.ocr.recognizers import create_recognizer
    selected = list(samples())
    model = None
    try:
        started = time.perf_counter()
        model = create_recognizer(config)
        loaded = time.perf_counter() - started
        texts, elapsed = model([crop for crop, _ in selected])
        if len(texts) != len(selected) or not any(item[0].strip() for item in texts):
            raise ValueError("GPU smoke dropped or blanked every crop")
        dump(args.output / "functional_gpu.json", dict(status="passed", config=config,
            load_seconds=loaded, recognition_seconds=elapsed, samples=[meta for _, meta in selected],
            results=texts, details=model.last_details, worker_runtime=model.worker_runtime,
            limit="Functional smoke only; no crop transcription gold, no recognition accuracy claim"))
    finally:
        if model is not None:
            model.close()
    dump(args.output / "qualification.json", dict(status="passed", strict_load=True, gpu_functional=True,
        native_cpu_parity=args.model == "vietocr_nhay_seq2seq", config_assumed=manifest["config_assumed"],
        provenance_limit=manifest["provenance_limit"]))
    print(f"QUALIFIED {args.model}", flush=True)


if __name__ == "__main__":
    main()
