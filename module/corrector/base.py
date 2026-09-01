from typing import Protocol, runtime_checkable


@runtime_checkable
class CorrectorBackend(Protocol):
    """Contract a swappable OCR text-correction backend must satisfy.

    Inputs and outputs are parallel lists: each input is one completed plain-
    text layout block, and each output is that same block after correction.
    Backends own tokenizer-aware chunking, batching, model lifetime and thread
    safety.
    """

    def correct_batch(self, texts: list[str]) -> list[str]: ...
