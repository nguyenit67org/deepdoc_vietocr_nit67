"""Ve bieu do F1 theo nhom field cho report PoC demo.

Nguon: ocr-collab/artifacts/evidence_full_inference_all_v3/metrics.csv
Chay: .venv/bin/python data/reports/poc_demo/plot_field_results.py
"""
import csv
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ART = pathlib.Path("ocr-collab/artifacts/evidence_full_inference_all_v3/metrics.csv")
OUT = pathlib.Path("data/reports/poc_demo/field_results_by_group.png")

GROUP_ORDER = ["Critical + required", "Critical + optional", "Non-critical + optional"]
GROUP_LABEL = {
    "Critical + required": "Required (7 fields)",
    "Critical + optional": "Critical + optional (4 fields)",
    "Non-critical + optional": "Non-critical + optional (2 fields)",
}
STATUS_COLOR = {
    "pass": "#2ca02c",
    "fail": "#d62728",
    "partial": "#7f7f7f",
}

rows = list(csv.DictReader(ART.open(encoding="utf-8")))
for r in rows:
    r["f1"] = float(r["f1"])
    r["status"] = r["status"].strip()

fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
fig.suptitle("Field F1 by group (full inference, 100 docs) - sorted descending", fontsize=13)

for ax, group in zip(axes, GROUP_ORDER):
    items = sorted([r for r in rows if r["group"] == group], key=lambda r: -r["f1"])
    names = [r["field_name"] for r in items]
    f1s = [r["f1"] for r in items]
    colors = [
        STATUS_COLOR["pass"] if r["status"] == "Đạt"
        else STATUS_COLOR["partial"] if "Chưa đánh giá" in r["status"]
        else STATUS_COLOR["fail"]
        for r in items
    ]
    y = range(len(names))
    bars = ax.barh(list(y), f1s, color=colors)
    ax.set_yticks(list(y))
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_title(GROUP_LABEL[group], loc="left", fontsize=11)
    ax.set_xlim(0, 1.05)
    for bar, v in zip(bars, f1s):
        ax.text(v + 0.015, bar.get_y() + bar.get_height() / 2, f"{v:.3f}",
                va="center", fontsize=9)
    target = 0.75 if group == "Non-critical + optional" else 0.95
    ax.axvline(target, color="black", linestyle="--", linewidth=1)
    ax.text(target, -0.75, f"target {target}", fontsize=8, ha="right", va="top")

axes[-1].set_xlabel("F1")
from matplotlib.patches import Patch
fig.legend(handles=[
    Patch(color=STATUS_COLOR["pass"], label="Dat target"),
    Patch(color=STATUS_COLOR["fail"], label="Chua dat"),
    Patch(color=STATUS_COLOR["partial"], label="Chua danh gia day du"),
], loc="lower right")
fig.tight_layout(rect=[0, 0.03, 1, 0.95])
OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, dpi=150)
print(f"saved {OUT}")
