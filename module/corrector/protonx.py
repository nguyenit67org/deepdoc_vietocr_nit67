import logging
import re
import threading

logger = logging.getLogger(__name__)

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?;])\s+")
_NUMBER_RE = re.compile(r"\d+")


class ProtonXCorrectorBackend:
    """Tokenizer-aware batched wrapper around ProtonX Legal Text Correction.

    The public unit is one completed layout-block string. Long strings are
    split at sentence boundaries (then words as a fallback), corrected in
    batches, and reassembled. Newlines are handled as hard boundaries so
    title/header formatting produced by the pipeline is preserved.
    """

    def __init__(
        self,
        model_name: str = "protonx-models/protonx-legal-tc",
        device: str | None = None,
        target_input_tokens: int = 140,
        max_input_tokens: int = 160,
        max_new_tokens: int = 160,
        batch_size: int = 8,
        num_beams: int = 10,
        preserve_numbers: bool = True,
    ):
        if target_input_tokens < 1:
            raise ValueError("corrector.target_input_tokens must be >= 1")
        if max_input_tokens < target_input_tokens:
            raise ValueError("corrector.max_input_tokens must be >= target_input_tokens")
        if max_new_tokens < 1:
            raise ValueError("corrector.max_new_tokens must be >= 1")
        if batch_size < 1:
            raise ValueError("corrector.batch_size must be >= 1")
        if num_beams < 1:
            raise ValueError("corrector.num_beams must be >= 1")

        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        self._device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self._model.to(self._device)
        self._model.eval()

        self.target_input_tokens = target_input_tokens
        self.max_input_tokens = max_input_tokens
        self.max_new_tokens = max_new_tokens
        self.batch_size = batch_size
        self.num_beams = num_beams
        self.preserve_numbers = preserve_numbers
        # One backend instance is shared by concurrent API requests. Neither
        # generation nor the underlying model is assumed to be thread-safe.
        self._lock = threading.Lock()
        logger.info("[device] Corrector (ProtonX %s): device=%s", model_name, self._device)

    def _token_count(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=True))

    def _split_by_words(self, text: str) -> list[str]:
        chunks: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if current and self._token_count(candidate) > self.target_input_tokens:
                chunks.append(current)
                current = word
            else:
                current = candidate

            # Extremely long OCR garbage may tokenize beyond the limit even
            # without whitespace. Split it by characters rather than silently
            # truncating model input.
            if current and self._token_count(current) > self.max_input_tokens:
                piece = ""
                for char in current:
                    candidate = piece + char
                    if piece and self._token_count(candidate) > self.target_input_tokens:
                        chunks.append(piece)
                        piece = char
                    else:
                        piece = candidate
                current = piece

        if current:
            chunks.append(current)
        return chunks

    def _split_line(self, line: str) -> list[str]:
        line = line.strip()
        if not line:
            return []
        if self._token_count(line) <= self.target_input_tokens:
            return [line]

        chunks: list[str] = []
        current = ""
        for sentence in _SENTENCE_BOUNDARY_RE.split(line):
            sentence = sentence.strip()
            if not sentence:
                continue
            if self._token_count(sentence) > self.target_input_tokens:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(self._split_by_words(sentence))
                continue

            candidate = f"{current} {sentence}".strip()
            if current and self._token_count(candidate) > self.target_input_tokens:
                chunks.append(current)
                current = sentence
            else:
                current = candidate

        if current:
            chunks.append(current)
        return chunks

    def _chunk_text(self, text: str) -> list[list[str]]:
        """Returns one chunk list per original line, preserving blank lines."""
        return [self._split_line(line) for line in text.split("\n")]

    def _accept(self, original: str, corrected: str) -> str:
        corrected = corrected.strip()
        if not corrected:
            return original
        if self.preserve_numbers and _NUMBER_RE.findall(original) != _NUMBER_RE.findall(corrected):
            logger.warning("To be rejected correction that changed numeric content: %r -> %r", original, corrected)
            # return original
        return corrected

    def correct_batch(self, texts: list[str]) -> list[str]:
        if not texts:
            return []

        structures = [self._chunk_text(text) for text in texts]
        flat_chunks = [chunk for lines in structures for line_chunks in lines for chunk in line_chunks]
        if not flat_chunks:
            return list(texts)

        corrected_chunks: list[str] = []
        with self._lock, self._torch.inference_mode():
            for start in range(0, len(flat_chunks), self.batch_size):
                batch = flat_chunks[start : start + self.batch_size]
                inputs = self._tokenizer(
                    batch,
                    return_tensors="pt",
                    padding=True,
                    truncation=False,
                ).to(self._device)
                longest = int(inputs["attention_mask"].sum(dim=1).max().item())
                if longest > self.max_input_tokens:
                    raise ValueError(f"Corrector produced a {longest}-token input; maximum is {self.max_input_tokens}")
                outputs = self._model.generate(
                    **inputs,
                    num_beams=self.num_beams,
                    num_return_sequences=1,
                    max_new_tokens=self.max_new_tokens,
                    early_stopping=True,
                )
                decoded = self._tokenizer.batch_decode(outputs, skip_special_tokens=True)
                if len(decoded) != len(batch):
                    raise RuntimeError(f"Corrector returned {len(decoded)} results for {len(batch)} inputs")
                corrected_chunks.extend(
                    self._accept(original, corrected) for original, corrected in zip(batch, decoded)
                )

        chunk_iter = iter(corrected_chunks)
        corrected_texts = []
        for lines in structures:
            corrected_lines = [" ".join(next(chunk_iter) for _ in line_chunks) for line_chunks in lines]
            corrected_texts.append("\n".join(corrected_lines))
        return corrected_texts
