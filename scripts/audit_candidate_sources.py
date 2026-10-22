"""Save public source evidence and explicit availability blockers for this cohort."""
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_20261021/source_audit"
SOURCES = {
    "viethandocr": ("hoangtranduchai/viethandocr", "31a43e083f5d83354bf1d4d24f82b70456185ecf"),
    "vietdoc": ("taiiswibu/VietdocOCR_fine_tuning", "26f9cfa322eb7a9928bac560150856dfe9865ff5"),
    "vnhtr": ("anhnh2002/vnhtr", "18c127441dea3cd731289c7b292ab0af2c0aefa8"),
}


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "candidate-model-source-audit"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (repo, revision) in SOURCES.items():
        folder = OUT / name
        folder.mkdir(exist_ok=True)
        for filename, url in {
            "tree.json": f"https://api.github.com/repos/{repo}/git/trees/{revision}?recursive=1",
            "releases.json": f"https://api.github.com/repos/{repo}/releases",
            "README.md": f"https://raw.githubusercontent.com/{repo}/{revision}/README.md",
        }.items():
            (folder / filename).write_bytes(fetch(url))
    for name, filename in (("viethandocr", "05_Evaluation_and_Inference.ipynb"),
                           ("viethandocr", "04_VietOCR_Training.ipynb"),
                           ("vietdoc", "models/README.md"), ("vietdoc", "scripts/download_models.py")):
        repo, revision = SOURCES[name]
        output_name = "models_README.md" if filename == "models/README.md" else Path(filename).name
        (OUT / name / output_name).write_bytes(fetch(f"https://raw.githubusercontent.com/{repo}/{revision}/{filename}"))
    audit = {
        "mode": "source/checkpoint availability audit, not inference results",
        "sources": {name: {"repo": repo, "revision": revision} for name, (repo, revision) in SOURCES.items()},
        "viethandocr": {"status": "blocked_missing_finetuned_weights", "evidence": ["viethandocr/tree.json", "viethandocr/releases.json", "viethandocr/05_Evaluation_and_Inference.ipynb"],
            "reason": "No checkpoint artifact in pinned Git tree or public GitHub releases. Inference notebook is a skeleton, not a published fine-tuned recognizer."},
        "vietdoc": {"status": "upstream_baseline_downloader_probe_started_finetuned_easyocr_unavailable", "evidence": ["vietdoc/tree.json", "vietdoc/releases.json", "vietdoc/README.md", "vietdoc/download_models.py"],
            "reason": "scripts/download_models.py publishes external baselines: doanhm/vgg_transformer and vudang449 best_ep11.pth, plus standard EasyOCR. Native downloader is being tested in an isolated source copy. Separate fine-tuned EasyOCR deployment package is not published in the pinned tree or releases. Do not conflate availability of baselines with availability of project fine-tuned weights."},
        "vnhtr": {"status": "public_weights_found", "candidates": ["vnhtr_vgg", "vnhtr_trocr"],
            "reason": "Native package exposes VGG Transformer and TrOCR with Rethinking Head; LFS weights in anhnh2002/vnhtr_weights. Source MIT; no separate model license identified."},
        "duyle": {"status": "public_weights_found", "repo": "duyle2408/trocr-vietnamese-handwriting", "revision": "96101b35a3e7bd9b066a77abe1b3e8631856e230", "license_card": "Apache-2.0",
            "reason": "ViT-large encoder plus PhoBERT decoder, different architecture and weights from tested Thaito98 checkpoint. Whole cached line diagnostic, no additional segmentation."},
        "preservation": "No training, GT edits, extraction changes, metric changes, default model promotion, or old artifact overwrites authorized.",
    }
    probe = ROOT / "scratch/ocr-recognizers/sources/vietdoc_download_probe_26f9cfa/models"
    if all((probe / variant / "provenance.json").exists() for variant in ("base", "handwriting")):
        audit["vietdoc"]["status"] = "native_downloader_passed_external_baselines_finetuned_easyocr_unavailable"
        audit["vietdoc"]["downloaded"] = {variant: json.loads((probe / variant / "provenance.json").read_text())
                                         for variant in ("base", "handwriting")}
    (OUT / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(OUT / "audit.json")


if __name__ == "__main__":
    main()
