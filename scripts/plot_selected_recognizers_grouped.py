"""Grouped vertical bars: six requested recognizers, 12 fields, F1 and NEM."""
import argparse
import csv
import json
import math
from pathlib import Path
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.plot_recognizer_field_metrics import load_runs, TITLES

SELECTED = (
    ("senocr", "SenOCR-Vi FP32"),
    ("vietocr_original_transformer", "VietOCR gốc Transformer"),
    ("fastocr_control", "FastOCR PyTorch (baseline)"),
    ("vietocr_handwriting", "VietOCR handwriting ONNX"),
    ("trocr_words", "TrOCR + tách từ [composite]"),
    ("nom_tesseract_spell", "Nôm Tesseract + spell"),
)


def selected_records(records, fields):
    selected = []
    for model, display in SELECTED:
        matches = [row for row in records if Path(row["artifact"]).name == model]
        if len(matches) != len(fields) or {row["field"] for row in matches} != set(fields):
            raise ValueError(f"Missing or duplicate field metrics for {model}")
        selected.extend({**row, "model": display} for row in matches)
    return selected


def bar_values(records, model, fields, metric):
    lookup = {row["field"]: row[metric] for row in records if row["model"] == model}
    return [100 * lookup[field] if lookup[field] is not None else math.nan for field in fields]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    records, fields, labels = load_runs()
    records = selected_records(records, fields)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    args.output.mkdir(parents=True, exist_ok=False)
    colors = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00", "#56B4E9"]
    x = np.arange(len(fields))
    width = .13
    tick_labels = [textwrap.fill(TITLES[field], 21) + f"\n({field})" for field in fields]
    for metric in ("f1", "nem"):
        figure, axis = plt.subplots(figsize=(25, 9))
        figure.subplots_adjust(left=.05, right=.99, bottom=.23, top=.82)
        for index, ((_, name), color) in enumerate(zip(SELECTED, colors)):
            values = bar_values(records, name, fields, metric)
            positions = x + (index - (len(SELECTED)-1)/2) * width
            bars = axis.bar(positions, values, width=width, color=color, label=name, zorder=3)
            for position, value, bar in zip(positions, values, bars):
                if math.isnan(value):
                    axis.text(position, 2, "N/A", ha="center", va="bottom", fontsize=7, rotation=90)
                else:
                    axis.annotate(f"{value:.1f}", (bar.get_x()+bar.get_width()/2, value),
                        xytext=(0, 3), textcoords="offset points", ha="center", va="bottom", fontsize=7)
        axis.set_xticks(x, tick_labels, fontsize=10)
        axis.set_xlim(-.6, len(fields)-.4)
        axis.set_ylim(0, 108)
        axis.set_yticks(range(0, 101, 10))
        axis.set_ylabel(metric.upper() + " (%)", fontsize=13)
        axis.set_xlabel("Trường thông tin", fontsize=12)
        axis.grid(axis="y", alpha=.22, zorder=0)
        axis.spines[["top", "right"]].set_visible(False)
        targets = ((85, "--", "PoC F1 85%"), (90, ":", "Stretch F1 90%")) if metric == "f1" else ((75, "--", "NEM target 75%"),)
        for target, style, label in targets:
            axis.axhline(target, linestyle=style, linewidth=.9, color="#555555", label=label, alpha=.75)
        figure.suptitle(f"{metric.upper()} theo 12 trường: so sánh 6 model", y=.98, fontsize=20, weight="bold")
        axis.set_title("100 PDF / 183 trang chọn / 6.619 crop | KIE hybrid, metric 2.2 | VietOCR Seq2Seq đã loại", fontsize=11, pad=12)
        figure.legend(*axis.get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(.5, .94), ncol=4,
            frameon=False, fontsize=11)
        figure.text(.05, .025, "Cùng GT và cache đã xác minh. Trục Y: phần trăm; N/A không phải 0. Nôm + spell có thêm hậu sửa. TrOCR có thêm tách từ (composite).\n"
            "Các đường target chỉ tham chiếu; đánh giá đạt còn cần precision, recall, hallucination và coverage.", fontsize=10)
        for extension in ("png", "svg"):
            figure.savefig(args.output / f"{metric}_grouped_12_fields.{extension}", dpi=180)
        plt.close(figure)
    with (args.output / "field_metrics.csv").open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    report = ["# F1 và NEM: 6 model theo 12 trường", "",
        "Trục X: trường thông tin. Mỗi nhóm có 6 cột model đứng cạnh nhau; trục Y: giá trị %. Loại VietOCR gốc Seq2Seq; thay OcrDoc bằng TrOCR theo yêu cầu. Chỉ vẽ lại kết quả có sẵn, không inference/rescore hay đổi GT.", "",
        "![F1](f1_grouped_12_fields.png)", "", "![NEM](nem_grouped_12_fields.png)", "",
        "Cùng 100 PDF / 183 trang chọn / 6.619 crop, metric 2.2; đã đối chiếu hash GT hiện tại, baseline/config/cache. Đây là KIE hybrid; trang không chọn giữ baseline OCR. Nôm Tesseract + spell có bước hậu sửa. TrOCR dùng whitespace word segmentation + nhận dạng từng mảnh + ghép dòng: đây là composite ablation, không phải recognizer-only swap. Kết quả có thể chịu lỗi segmentation và không đại diện TrOCR trên word crops chuẩn.", ""]
    for metric in ("f1", "nem"):
        report += [f"## {metric.upper()} (%)", "", "| Trường | " + " | ".join(name for _, name in SELECTED) + " |",
            "|---|" + "---:|" * len(SELECTED)]
        for field in fields:
            values = []
            for _, name in SELECTED:
                value = next(row[metric] for row in records if row["model"] == name and row["field"] == field)
                values.append("N/A" if value is None else f"{value*100:.2f}")
            report.append(f"| {TITLES[field]} ({field}) | " + " | ".join(values) + " |")
        report.append("")
    report += ["F1 target PoC 85%, stretch 90%; precision và recall cũng phải đạt riêng. NEM target 75%. Hallucination/coverage kiểm tra riêng, N/A không phải 0. receiverDate ngoài phạm vi. Visual root-cause review còn pending.", "",
        "[CSV số liệu](field_metrics.csv) | [Cấu hình các cohort trước](../final/REPORT.md) | [Nôm raw/spell](../../recognizer_ab_nom_20261016/REPORT.md)", ""]
    (args.output / "REPORT.md").write_text("\n".join(report))
    (args.output / "manifest.json").write_text(json.dumps(dict(status="completed", metric_version="2.2",
        models=[name for _, name in SELECTED], fields=fields, rows=len(records),
        orientation="vertical", x_axis="field", y_axis="percent", grouped_by="model", gt_fingerprints=labels), indent=2) + "\n")
    print(args.output / "REPORT.md")


if __name__ == "__main__":
    main()
