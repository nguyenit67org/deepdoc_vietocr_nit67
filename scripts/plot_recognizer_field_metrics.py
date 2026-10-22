"""Plot comparable completed recognizers: per-field F1/NEM, no inference."""
import argparse
import csv
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_cached_ocr_equivalence import sha256

RUNS = (
    ("FastOCR (PyTorch, dòng)", "recognizer_ab_nom_20261016/fastocr_control"),
    ("OcrDoc Run 6", "recognizer_ab_20261015/ocrdoc"),
    ("VietOCR handwriting ONNX", "recognizer_ab_20261015/vietocr_handwriting"),
    ("HTR-ConvText", "recognizer_ab_20261015/htr_convtext"),
    ("SenOCR FP32", "recognizer_ab_20261015/senocr"),
    ("AkaOCR public", "recognizer_ab_additional_20261015/akaocr"),
    ("VietOCR gốc Seq2Seq", "recognizer_ab_additional_20261015/vietocr_original_seq2seq"),
    ("VietOCR gốc Transformer", "recognizer_ab_additional_20261015/vietocr_original_transformer"),
    ("VietOCR DungHugging", "recognizer_ab_additional_20261015/vietocr_dunghugging"),
    ("FastOCR + tách từ [composite]", "recognizer_ab_trocr_20261015/fastocr_words"),
    ("TrOCR + tách từ [composite]", "recognizer_ab_trocr_20261015/trocr_words"),
    ("Nôm Tesseract raw", "recognizer_ab_nom_20261016/nom_tesseract_raw"),
    ("Nôm Tesseract + spell", "recognizer_ab_nom_20261016/nom_tesseract_spell"),
)
TITLES = {
    "type": "Loại văn bản", "title": "Trích yếu / tiêu đề", "code": "Số, ký hiệu văn bản",
    "documentDate": "Ngày ban hành", "officeSender": "Cơ quan ban hành",
    "recipients": "Nơi nhận cuối văn bản", "signer": "Họ tên người ký",
    "priority_level": "Độ khẩn", "security_level": "Độ mật",
    "first_recipients": "Kính gửi đầu văn bản", "signer_title": "Chức danh người ký", "province": "Địa danh",
}


def read(path):
    return json.loads(path.read_text())


def metric_number(value):
    if value in (None, ""):
        return None
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError(f"Invalid F1/NEM: {value}")
    return number


def load_runs():
    import benchmark as b
    current_cases = {case.document_id: case for case in b.load_cases(b.DEFAULT_CLEAN_DIR, b.DEFAULT_DATA_ROOT)}
    labels, records, reference_inputs = None, [], None
    for name, relative in RUNS:
        folder = ROOT / "ocr-collab/artifacts" / relative
        manifest, summary, fingerprint = [read(folder / file) for file in ("manifest.json", "summary.json", "run_fingerprint.json")]
        if manifest["status"] != "completed" or summary["metric_version"] != b.METRIC_VERSION:
            raise ValueError(f"Incomplete/incompatible run: {relative}")
        frozen_inputs = {key: fingerprint[key] for key in (
            "baseline_sha256", "baseline_predictions_sha256", "config_sha256", "cache_manifest_sha256")}
        if reference_inputs is None:
            reference_inputs = frozen_inputs
        if frozen_inputs != reference_inputs:
            raise ValueError("Baseline/config/crop-cache provenance differs across runs")
        if labels is None:
            labels = fingerprint["labels"]
            if any(sha256(current_cases[doc].json_path) != digest for doc, digest in labels.items()):
                raise ValueError("Current GT changed; explicit rescore required before plotting")
        if fingerprint["labels"] != labels:
            raise ValueError("GT differs across runs")
        if (summary["documents"], summary["selected_pages"], summary["total_crops"]) != (100, 183, 6619):
            raise ValueError("Coverage differs across runs")
        with (folder / "evaluation/candidate/metrics.csv").open() as handle:
            fields = {row["field_name"]: row for row in csv.DictReader(handle)}
        if set(fields) != set(b.FIELDS):
            raise ValueError("Expected exactly the 12 scored fields")
        for field in b.FIELDS:
            row = fields[field]
            records.append(dict(model=name, field=field, field_label=TITLES[field], group=row["group"],
                f1=metric_number(row["f1"]), nem=metric_number(row["nem"]),
                precision=metric_number(row["precision"]), recall=metric_number(row["recall"]),
                gt_present_count=int(row["gt_present_count"]), artifact=relative))
    return records, list(b.FIELDS), labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    records, fields, labels = load_runs()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    args.output.mkdir(parents=True, exist_ok=False)
    individual = args.output / "fields"
    individual.mkdir()
    colors = list(plt.get_cmap("tab20").colors[:len(RUNS)])

    def draw(axis, field, metric):
        rows = [row for row in records if row["field"] == field]
        values = [100 * row[metric] if row[metric] is not None else 0 for row in rows]
        axis.barh(range(len(rows)), values, color=colors, height=.7)
        axis.set_yticks(range(len(rows)), [row["model"] for row in rows], fontsize=8)
        axis.invert_yaxis()
        axis.set_xlim(0, 108)
        axis.set_xticks([0, 25, 50, 75, 100])
        axis.set_xlabel(metric.upper() + " (%)", fontsize=9)
        axis.set_title(f"{TITLES[field]} ({field})\n{rows[0]['group']}", fontsize=10)
        axis.grid(axis="x", alpha=.2)
        axis.set_axisbelow(True)
        for i, (value, row) in enumerate(zip(values, rows)):
            axis.text(value + 1, i, f"{value:.1f}" if row[metric] is not None else "N/A", va="center", fontsize=8)
        for threshold, color, style in ((85, "#bb6600", "--"), (90, "#8a2be2", ":")) if metric == "f1" else ((75, "#bb6600", "--"),):
            axis.axvline(threshold, color=color, linestyle=style, linewidth=1)

    for metric in ("f1", "nem"):
        figure, axes = plt.subplots(4, 3, figsize=(30, 25), constrained_layout=True)
        figure.suptitle(f"{metric.upper()} theo 12 trường | 13 cấu hình | 100 PDF / 183 trang chọn / 6.619 crop\n"
            "KIE hybrid; composite tách từ không phải recognizer-only. N/A không phải 0.", fontsize=16)
        for axis, field in zip(axes.flat, fields):
            draw(axis, field, metric)
        legend = ([Line2D([0], [0], color="#bb6600", linestyle="--", label="PoC F1: 85%"),
                   Line2D([0], [0], color="#8a2be2", linestyle=":", label="Stretch F1: 90%")]
                  if metric == "f1" else [Line2D([0], [0], color="#bb6600", linestyle="--", label="NEM target: 75%")])
        figure.legend(handles=legend, loc="outside lower center", ncol=2)
        for suffix in ("png", "svg"):
            figure.savefig(args.output / f"{metric}_12_fields.{suffix}", dpi=160)
        plt.close(figure)
    for field in fields:
        figure, axes = plt.subplots(1, 2, figsize=(18, 7), constrained_layout=True)
        draw(axes[0], field, "f1")
        draw(axes[1], field, "nem")
        figure.savefig(individual / f"{field}.png", dpi=150)
        plt.close(figure)
    with (args.output / "field_metrics.csv").open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    text = ["# F1 và NEM từng model, theo 12 trường", "",
        "13 cấu hình, cùng 100 PDF / 183 trang chọn / 6.619 crop, metric 2.2 và cùng GT hiện tại đã kiểm tra hash. Đây là KIE hybrid; trang không chọn giữ OCR baseline. receiverDate không chấm. Không phải recognition CER/WER.", "",
        "FastOCR whole-line chỉ hiển thị một control mới nhất. FastOCR/TrOCR tách từ là composite ablation; Nôm + spell có thêm hậu sửa. Không xem tất cả là recognizer-only ranking.", "",
        "![F1 12 trường](f1_12_fields.png)", "", "![NEM 12 trường](nem_12_fields.png)", "",
        "F1 target PoC 85%, stretch 90%; precision và recall cũng phải đạt riêng. NEM target 75%. Trường thiếu mẫu số hiển thị N/A, không tính là đạt. Bảng/biểu đồ không thay thế kiểm tra hallucination hoặc coverage.", ""]
    for field in fields:
        text += [f"## {TITLES[field]} ({field})", "", f"[Biểu đồ riêng](fields/{field}.png)", "",
            "| Model | F1 | NEM | GT có giá trị |", "|---|---:|---:|---:|"]
        for row in [r for r in records if r["field"] == field]:
            def percent(value):
                return "N/A" if value is None else f"{100*value:.2f}%"
            text.append(f"| {row['model']} | {percent(row['f1'])} | {percent(row['nem'])} | {row['gt_present_count']} |")
        text.append("")
    text += ["## Chi tiết cấu hình, timing và KIE", "",
        "- [Các cohort trước](../final/REPORT.md)",
        "- [Nôm Tesseract raw / spell](../../recognizer_ab_nom_20261016/REPORT.md)",
        "- [Bảng CSV đầy đủ](field_metrics.csv)", "",
        "Không đổi GT, metric hay inference để vẽ biểu đồ. Visual root-cause review đầy đủ vẫn pending. Source artifact cho từng dòng được ghi trong CSV.", ""]
    (args.output / "REPORT.md").write_text("\n".join(text))
    (args.output / "manifest.json").write_text(json.dumps(dict(status="completed", models=len(RUNS), fields=len(fields),
        metric_version="2.2", gt_fingerprints=labels, artifacts=dict(RUNS), rows=len(records)), indent=2) + "\n")
    print(args.output / "REPORT.md")


if __name__ == "__main__":
    main()
