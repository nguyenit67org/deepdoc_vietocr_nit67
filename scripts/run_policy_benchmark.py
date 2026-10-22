"""Run the standard full benchmark with isolated pipeline/debug outputs."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ocr-collab"))

import benchmark
import module.pipeline as pipeline


if __name__ == "__main__":
    args = benchmark.parse_args()
    if args.output_dir is None:
        raise SystemExit("--output-dir is required for isolated runs")
    original = pipeline.load_pipeline_conf

    def isolated_config():
        config = original()
        config.setdefault("output", {})["dir"] = str(args.output_dir.resolve() / "pipeline_outputs")
        config.setdefault("debug", {})["dir"] = str(args.output_dir.resolve() / "debug_outputs")
        return config

    pipeline.load_pipeline_conf = isolated_config
    benchmark.run_benchmark(args)
