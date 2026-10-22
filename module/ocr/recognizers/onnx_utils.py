import numpy as np


def session(path, device="cpu", device_id=0, threads=2):
    import onnxruntime as ort
    providers = ["CPUExecutionProvider"]
    if device == "cuda":
        if "CUDAExecutionProvider" not in ort.get_available_providers():
            raise RuntimeError("CUDA ONNX provider requested but unavailable")
        providers.insert(0, ("CUDAExecutionProvider", {"device_id": device_id}))
    elif device != "cpu":
        raise ValueError("ONNX device must be cpu or cuda")
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    model = ort.InferenceSession(str(path), sess_options=options, providers=providers)
    if device == "cuda" and "CUDAExecutionProvider" not in model.get_providers():
        raise RuntimeError("ONNX silently fell back to CPU despite a CUDA request")
    return model


def ctc_decode(probabilities, vocabulary, blank=0):
    if probabilities.ndim != 3 or probabilities.shape[-1] != len(vocabulary) or not np.isfinite(probabilities).all():
        raise ValueError("CTC output/vocabulary shape mismatch")
    results = []
    for sequence in probabilities:
        ids = sequence.argmax(-1)
        retained = [i for i, token in enumerate(ids) if token != blank and (i == 0 or token != ids[i - 1])]
        text = "".join(vocabulary[ids[i]] for i in retained)
        score = float(np.mean([sequence[i, ids[i]] for i in retained])) if retained else 0.0
        results.append((text, score))
    return results
