"""Native line inference for pinned Duyle TrOCR and VNHTR public JIT models."""
import ast
from pathlib import Path

from .base import BatchedRecognizer, RecognitionResult


class DuyleTrOcrRecognizer(BatchedRecognizer):
    has_native_confidence = False

    def __init__(self, model_dir, device_id=0, device="cuda", max_batch_size=2):
        super().__init__(max_batch_size)
        import torch
        from transformers import AutoTokenizer, ViTImageProcessor, VisionEncoderDecoderModel
        if device not in ("cuda", "cpu"):
            raise ValueError("Unsupported device")
        self.device = torch.device(f"cuda:{device_id}" if device == "cuda" else "cpu")
        self.processor = ViTImageProcessor.from_pretrained(model_dir, local_files_only=True)
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)
        self.model, info = VisionEncoderDecoderModel.from_pretrained(model_dir,
            local_files_only=True, torch_dtype=torch.float32, attn_implementation="eager", output_loading_info=True)
        if info.get("missing_keys") or info.get("mismatched_keys") or info.get("error_msgs"):
            raise ValueError(f"Incomplete Duyle checkpoint: {info}")
        self.model.to(self.device).eval()

    def _recognize_batch(self, images):
        import torch
        pixels = self.processor(images=images, return_tensors="pt").pixel_values.to(self.device)
        # Retain checkpoint generation_config: beam=4, max_length=64, length
        # penalty=2, no_repeat_ngram_size=3, early_stopping=True.
        with torch.inference_mode():
            sequences = self.model.generate(pixels, do_sample=False)
        texts = self.tokenizer.batch_decode(sequences, skip_special_tokens=True)
        eos = self.model.generation_config.eos_token_id
        return [RecognitionResult(text, truncated=eos not in ids.tolist()[1:],
                    metadata={"token_ids": ids.tolist(), "input_protocol": "whole cached line; no segmentation",
                              "generation_config": self.model.generation_config.to_dict()})
                for text, ids in zip(texts, sequences)]


def vnhtr_vocab(source):
    """Read the literal character list, without executing upstream Python."""
    tree = ast.parse(Path(source).read_text())
    tokenizer = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Tokenizer")
    init = next(node for node in tokenizer.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    assignment = next(node for node in init.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "vocab" for target in node.targets))
    vocab = ast.literal_eval(assignment.value)
    if not isinstance(vocab, list) or not all(isinstance(char, str) and len(char) == 1 for char in vocab):
        raise ValueError("Unexpected VNHTR vocabulary")
    return ["pad", "<sos>", "<eos>", "<unk>"] + vocab


def decode_vnhtr(tokens, vocab):
    output = []
    for token in tokens:
        if token == 2:
            break
        if token not in (0, 1, 3):
            output.append(vocab[token])
    return "".join(output)


def vnhtr_weight_prefix(variant, rethinking_head):
    if variant not in ("vgg", "trocr") or type(rethinking_head) is not bool:
        raise ValueError("Unsupported VNHTR family/head selection")
    return {("vgg", False): "vt", ("vgg", True): "vta",
            ("trocr", False): "tr", ("trocr", True): "tra"}[variant, rethinking_head]


class VnhtrJitRecognizer(BatchedRecognizer):
    has_native_confidence = False

    def __init__(self, model_dir, variant, device_id=0, device="cuda", max_batch_size=4, rethinking_head=True):
        super().__init__(max_batch_size)
        import torch
        if variant not in ("vgg", "trocr") or device not in ("cuda", "cpu"):
            raise ValueError("Unsupported VNHTR variant/device")
        self.variant = variant
        self.rethinking_head = rethinking_head
        self.device = torch.device(f"cuda:{device_id}" if device == "cuda" else "cpu")
        folder = Path(model_dir)
        prefix = vnhtr_weight_prefix(variant, rethinking_head)
        self.encoder = torch.jit.load(str(folder / f"{prefix}_encoder.pt"), map_location=self.device).eval()
        self.decoder = torch.jit.load(str(folder / f"{prefix}_decoder.pt"), map_location=self.device).eval()
        if variant == "vgg":
            self.vocab = vnhtr_vocab(folder / "upstream_tools.py.txt")
        else:
            from transformers import AutoTokenizer, ViTImageProcessor
            self.tokenizer = AutoTokenizer.from_pretrained(folder / "tokenizer", local_files_only=True, trust_remote_code=False)
            self.processor = ViTImageProcessor.from_pretrained(folder / "processor", local_files_only=True)

    def _pixels(self, images):
        import numpy as np
        import torch
        from PIL import Image, ImageOps
        if self.variant == "trocr":
            return self.processor(images=images, return_tensors="pt").pixel_values.to(self.device)
        arrays, widths = [], []
        for image in images:
            width = int(32 * image.width / image.height)
            if width < 1:
                raise ValueError("VNHTR native resized width is zero")
            resized = image.convert("RGB").resize((width, 32), Image.Resampling.LANCZOS)
            # Native upstream pads to 768, or crops the right edge if wider.
            padded = ImageOps.expand(resized, border=(0, 0, 768 - width, 0), fill="white")
            arrays.append(np.asarray(padded).transpose(2, 0, 1) / 255)
            widths.append(width)
        return torch.tensor(np.asarray(arrays), dtype=torch.float32, device=self.device)[:, :, :, :max(widths)]

    def _recognize_batch(self, images):
        import torch
        pixels = self._pixels(images)
        sos, limit = (1, 128) if self.variant == "vgg" else (0, 35)
        ids = torch.full((len(images), 1), sos, dtype=torch.long, device=self.device)
        with torch.inference_mode(), torch.jit.optimized_execution(True):
            memory = self.encoder(pixels)
            for _ in range(limit + 1):
                if self.variant == "vgg":
                    if (ids == 2).any(dim=1).all():
                        break
                elif (ids[:, -1] == 2).all():
                    break
                mask = torch.triu(torch.full((ids.shape[1], ids.shape[1]), float("-inf"), device=self.device), diagonal=1)
                target = ids.T if self.variant == "vgg" else ids
                logits = self.decoder(target, memory, mask)
                # Preserve native VGG softmax/topk-5 selection (including tie behavior).
                if self.variant == "vgg":
                    next_ids = logits.softmax(-1).cpu().topk(5).indices[:, -1, 0].to(self.device)
                else:
                    next_ids = logits[:, -1, :].softmax(-1).argmax(-1)
                ids = torch.cat((ids, next_ids[:, None]), dim=1)
        rows = ids.cpu().tolist()
        texts = ([decode_vnhtr(row, self.vocab) for row in rows] if self.variant == "vgg"
                 else self.tokenizer.batch_decode(rows, skip_special_tokens=True))
        return [RecognitionResult(text, truncated=2 not in row[1:], metadata={"token_ids": row,
                    "variant": self.variant, "rethinking_head": self.rethinking_head, "native_max_seq_length": limit,
                    "input_protocol": "whole cached line; no segmentation",
                    "native_right_crop": self.variant == "vgg" and int(32 * image.width / image.height) > 768})
                for text, row, image in zip(texts, rows, images)]
