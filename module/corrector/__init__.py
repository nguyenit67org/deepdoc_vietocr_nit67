from .base import CorrectorBackend


def get_corrector_backend(conf: dict) -> CorrectorBackend | None:
    """Builds the configured corrector, or returns None when disabled."""
    corrector_conf = conf.get("corrector", {})
    if not corrector_conf.get("enabled", False):
        return None

    backend = corrector_conf.get("backend", "protonx")
    if backend == "protonx":
        # Keep transformers/model loading out of module import and disabled
        # configurations, matching the lazy factory pattern used by table and
        # extract backends.
        from .protonx import ProtonXCorrectorBackend

        return ProtonXCorrectorBackend(
            model_name=corrector_conf.get("model_name", "protonx-models/protonx-legal-tc"),
            device=corrector_conf.get("device"),
            target_input_tokens=corrector_conf.get("target_input_tokens", 140),
            max_input_tokens=corrector_conf.get("max_input_tokens", 160),
            max_new_tokens=corrector_conf.get("max_new_tokens", 160),
            batch_size=corrector_conf.get("batch_size", 8),
            num_beams=corrector_conf.get("num_beams", 10),
            preserve_numbers=corrector_conf.get("preserve_numbers", True),
        )
    raise ValueError(f"Unknown corrector backend: {backend!r}")


__all__ = [
    "CorrectorBackend",
    "get_corrector_backend",
]
