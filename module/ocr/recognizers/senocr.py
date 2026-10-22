"""SenOCR element-level OCR only; no page parser, detector, or external API."""
from pathlib import Path

from .base import BatchedRecognizer, RecognitionResult


class SenOcrRecognizer(BatchedRecognizer):
    has_native_confidence = False

    def __init__(self, model_dir, device_id=0, device="cuda", max_batch_size=1,
                 dtype="float32", max_new_tokens=256):
        super().__init__(max_batch_size)
        if type(max_new_tokens) is not int or max_new_tokens < 1:
            raise ValueError("max_new_tokens must be positive")
        import torch
        from transformers import AutoProcessor, AutoModelForImageTextToText
        if dtype not in ("float32", "float16", "bfloat16"):
            raise ValueError("Unsupported SenOCR dtype")
        self.max_new_tokens = max_new_tokens
        self.device = torch.device(f"cuda:{device_id}" if device == "cuda" else device)
        self.dtype = getattr(torch, dtype)
        root = str(Path(model_dir).resolve())
        # Use Transformers' native implementation, as recommended by the model card.
        # Downloaded legacy custom code has incompatible APIs across Transformers releases.
        self.processor = AutoProcessor.from_pretrained(root, trust_remote_code=False, local_files_only=True, use_fast=False)
        self.model, loading = AutoModelForImageTextToText.from_pretrained(root, trust_remote_code=False,
            local_files_only=True, dtype=self.dtype, attn_implementation="eager", output_loading_info=True)
        if loading.get("missing_keys") or loading.get("mismatched_keys") or loading.get("error_msgs"):
            raise ValueError(f"SenOCR checkpoint did not fully initialize model: {loading}")
        self.model = self.model.to(self.device).eval()
        self.processor.tokenizer.padding_side = "left"

    def _recognize_batch(self, images):
        import torch
        # Per-image generation avoids unvalidated multimodal padding semantics.
        results = []
        for image in images:
            messages = [{"role": "user", "content": [{"type": "image", "image": image},
                                                      {"type": "text", "text": "OCR:"}]}]
            inputs = self.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                return_dict=True, return_tensors="pt").to(self.device)
            for key, value in inputs.items():
                if isinstance(value, torch.Tensor) and value.is_floating_point():
                    inputs[key] = value.to(self.dtype)
            with torch.inference_mode():
                output = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False, num_beams=1, use_cache=True)
            generated = output[0, inputs["input_ids"].shape[-1]:]
            text = self.processor.decode(generated, skip_special_tokens=True)
            eos = self.model.generation_config.eos_token_id
            eos = [eos] if isinstance(eos, int) else (eos or [])
            finished = any(int(token) in eos for token in generated)
            results.append(RecognitionResult(text, None, truncated=not finished and len(generated) >= self.max_new_tokens,
                metadata={"prompt": "OCR:", "generated_tokens": len(generated), "dtype": str(self.dtype)}))
        return results
