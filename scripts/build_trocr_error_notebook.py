"""Build report + executed offline notebook from frozen TrOCR audit artifacts."""
import argparse
from collections import Counter
import datetime
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.analyze_trocr_saved_errors import read, write, csv_write, EXPERIMENT, RUNS
from scripts.check_cached_ocr_equivalence import sha256


def build_audit(output):
    assets=ROOT/"scratch/ocr-recognizers/models/trocr_thaito98"
    generation,config,tokenizer=[read(assets/name) for name in ("generation_config.json","config.json","tokenizer.json")]
    vocab=tokenizer["model"]["vocab"]
    notebook=read(output/"source_reference/TrOCR.ipynb")
    snippets=[]
    for index in (22,24,26):
        source="".join(notebook["cells"][index]["source"])
        snippets.append(dict(cell_index_0based=index,source=source))
    write(output/"source_reference/training_and_eval_snippets.json",snippets)
    if not all(token in snippets[-1]["source"] for token in ("num_beams", "= 4", "processor.tokenizer.cls_token_id")):
        raise ValueError("Upstream evaluation source changed")
    for name in ("config.json","generation_config.json","processor_config.json","tokenizer.json","tokenizer_config.json","model.safetensors"):
        expected=read(assets/"download_manifest.json")["artifacts"][name]["sha256"]
        if sha256(assets/name)!=expected:
            raise ValueError(f"Downloaded checkpoint asset changed: {name}")
    audit=dict(
        checkpoint_repo="Thaito98/vietnamese-handwriting-ocr",
        revision=read(assets/"download_manifest.json")["revision"],
        checkpoint_sha256=read(assets/"download_manifest.json")["artifacts"]["model.safetensors"]["sha256"],
        upstream_reports_finetuning=True,base_model="microsoft/trocr-base-handwritten",
        training_dataset="HANDS-VNOnDB, word-level tablet handwriting",
        upstream_epochs=10,upstream_training_batch_size=64,local_finetuning_performed=False,
        published_word_accuracy_percent=94.42,published_cer_percent=2.30,
        published_metrics_note="Author-reported on 11,064 isolated VNOnDB test words with beam=4; not reproduced or comparable to local KIE.",
        saved_generation_config=generation,top_level_config_decoder_start=config["decoder_start_token_id"],
        tokenizer_cls_token_id=vocab["<s>"],tokenizer_sep_token_id=vocab["</s>"],
        benchmark=dict(decoder_start_token_id=generation["decoder_start_token_id"],num_beams=1,max_new_tokens=64,
                       no_repeat_ngram_size=generation.get("no_repeat_ngram_size",0),use_cache=True),
        upstream_test=dict(decoder_start_token_id=vocab["<s>"],num_beams=4,max_new_tokens=32,no_repeat_ngram_size=3),
        causal_status="Confirmed config discrepancy and saved token prefix, NOT a measured cause or effect size. No inference rerun.")
    write(output/"decoding_audit.json",audit)
    return audit


def finalize_reviews(output):
    cases=read(output/"selected_cases.json")
    reviews=read(output/"visual_reviews.json")
    lookup={r["case_id"]:r for r in reviews}
    if len(lookup)!=30 or set(lookup)!={r["case_id"] for r in cases}:
        raise ValueError("Exactly one actual visual review is required per selected case")
    recorded=datetime.datetime.now().astimezone().isoformat()
    ledger=[]
    for case in cases:
        image=output/"evidence"/(case["case_id"]+".png")
        ledger.append(dict(case_id=case["case_id"],document_id=case["document_id"],
            physical_page_index_0based=case["page_index_0based"],crop_index=case["crop_index"],
            evidence_path=str(image.relative_to(output)),image_sha256=sha256(image),
            viewed_via="functions.read image tool in this conversation",review_recorded_at=recorded,
            timestamp_note="Record creation time, not a fabricated exact image-view timestamp",
            review_scope="Visual qualitative check of parent/word boundaries and selected decoded words; not full transcription GT"))
    csv_write(output/"image_view_ledger.csv",ledger)
    rows=[dict(case_id=case["case_id"],selection_stratum=case["selection_stratum"],
               document_id=case["document_id"],page_index_0based=case["page_index_0based"],crop_index=case["crop_index"],
               **{k:v if not isinstance(v,list) else ";".join(v) for k,v in lookup[case["case_id"]].items() if k!="case_id"}) for case in cases]
    csv_write(output/"visual_reviews.csv",rows)
    return cases,reviews


def make_plots(output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    parents=pd.read_csv(output/"parent_crop_diagnostics.csv",keep_default_na=False)
    words=pd.read_csv(output/"word_diagnostics.csv",keep_default_na=False)
    metrics=pd.read_csv(output/"field_metrics.csv")
    figure,axes=plt.subplots(1,3,figsize=(18,5),layout="constrained")
    axes[0].hist(parents["segments"],bins=range(0,int(parents["segments"].max())+2),color="#0072B2")
    axes[0].set(title="Số mảnh / parent crop",xlabel="Số mảnh",ylabel="Số parent crops")
    axes[1].hist(words["aspect_ratio"],bins=70,range=(0,20),color="#009E73")
    axes[1].set(title="Tỉ lệ rộng/cao mảnh (chỉ hiển thị ≤20)",xlabel="Width / height",ylabel="Số mảnh")
    axes[1].axvline(.35,color="red",linestyle="--")
    axes[1].axvline(5,color="red",linestyle="--")
    names=["A: FastOCR dòng","B: FastOCR mảnh","C: TrOCR mảnh"]
    summary=read(output/"summary.json")
    axes[2].bar(names,[summary["runs"][run]["document_success"]["passed_documents"] for run in RUNS],color=["#0072B2","#E69F00","#D55E00"])
    axes[2].set(title="Document Pass: measured KIE",ylabel="Documents / 100",ylim=(0,100))
    figure.suptitle("Geometry flags là dấu hiệu rủi ro, không phải lỗi segmentation đã được gán nhãn")
    figure.savefig(output/"diagnostic_overview.png",dpi=150)
    plt.close(figure)
    figure,axes=plt.subplots(2,1,figsize=(20,10),layout="constrained")
    names={"fastocr_control":"A FastOCR line","fastocr_words":"B FastOCR words","trocr_words":"C TrOCR words"}
    for axis,metric in zip(axes,("f1","nem")):
        table=metrics.pivot(index="field_name",columns="model",values=metric).reindex(
            index=metrics[metrics.model=="fastocr_control"].field_name,columns=list(RUNS))*100
        table.rename(columns=names).plot.bar(ax=axis,rot=30)
        axis.set(ylabel=metric.upper()+" (%)",ylim=(0,105),xlabel="")
        axis.grid(axis="y",alpha=.2)
    figure.savefig(output/"kie_f1_nem.png",dpi=150)
    plt.close(figure)


def make_report(output,summary,audit,cases,reviews):
    import pandas as pd
    from scripts.plot_recognizer_field_metrics import TITLES
    metrics=pd.read_csv(output/"field_metrics.csv")
    tags=Counter(tag for review in reviews for tag in review["tags"])
    lines=["# TrOCR: phân tích lỗi tách từ và nhận dạng", "",
        "## Kết luận ngắn", "",
        "1. **Checkpoint đã được tác giả fine-tune trên chữ viết tay tiếng Việt VNOnDB ở mức từng từ; chưa fine-tune thêm trên dữ liệu hành chính của mình.** Đây không phải bản Microsoft tiếng Anh nguyên gốc.",
        "2. **Có lệch decoding so với notebook gốc:** benchmark bắt đầu bằng token 2, upstream test dùng cls_token_id=0. Benchmark greedy beam=1/max_new_tokens=64/no_repeat_ngram=0; upstream test beam=4/max_new_tokens=32/no_repeat_ngram=3. Không được gọi lượt cũ là tái lập đúng cấu hình đánh giá upstream.",
        "3. **Có lỗi segmentation quan sát được**, gồm gom nhiều từ thành một mảnh, cắt rời chữ số/dấu câu, ghép khoảng trắng phá mã/ngày. Đồng thời có lỗi đọc ngay trên các word crops có ranh giới hợp lý.",
        "4. **0/100 Document Pass chỉ mô tả composite và cấu hình đã đo**, không chứng minh TrOCR chưa fine-tune hay không có khả năng đọc tiếng Việt. Chưa thể phân rã mức ảnh hưởng của decoding/domain/segmentation nếu chưa chạy đối chứng có kiểm soát.", "",
        "## Phạm vi và tính toàn vẹn", "",
        "Chỉ phân tích offline ảnh/output đã lưu; không gọi model, không thay GT, crop, extractor hoặc prediction. Cùng 100 documents / 183 trang chọn / 6.619 parent line crops; trang không chọn giữ baseline OCR (hybrid diagnostic). Cùng metric2.2 và GT hiện tại đã kiểm tra hashes. B và C có cùng toàn bộ parent/box/word hashes và thứ tự: 52.542 mảnh, **không đồng nghĩa 52.542 từ được tách đúng**.", "",
        "## Fine-tuning và nguồn", "",
        f"- Source/checkpoint: `Thaito98/vietnamese-handwriting-ocr`, revision `{audit['revision']}`.",
        f"- Weight SHA-256: `{audit['checkpoint_sha256']}`; đã kiểm tra lại file local khớp download manifest.",
        "- Base `microsoft/trocr-base-handwritten`; notebook gốc khai báo 10 epochs, batch64, learning rate2e-5, dữ liệu HANDS-VNOnDB từng từ từ bảng viết stylus. Không có local training trong benchmark này.",
        "- Tác giả công bố Word Accuracy94,42% / CER2,30% trên 11.064 word test samples, beam4. Đây là số tác giả, không tự tái lập; khác domain, granularity và decoding với KIE hiện tại. 0 Document Pass không phải 0 word accuracy.",
        "- [README nguồn đã pin](source_reference/README.md), [notebook training/eval gốc, chỉ lưu để đọc](source_reference/TrOCR.ipynb), [trích cell22/24/26, index0-based](source_reference/training_and_eval_snippets.json). Source notebook **không được execute** trong task này.", "",
        "## Lệch decoding: bằng chứng cụ thể", "",
        "| Tham số | Benchmark đã chạy | Notebook upstream test |", "|---|---:|---:|",
        "| decoder_start_token_id | 2, từ generation_config.json | 0, tokenizer.cls_token_id |",
        "| num_beams | 1 | 4 |", "| max_new_tokens | 64 | 32 |", "| no_repeat_ngram_size | 0 mặc định | 3 |", "",
        "Top-level config.json ghi decoder_start=0, nhưng saved generation_config.json ghi2 và adapter không override token khởi đầu. **Cả52.542 sequences lưu đều bắt đầu `[2,0,...]`**, xác nhận cấu hình thực tế. Prefix này là bằng chứng lệch, không phải bằng chứng định lượng lỗi do prefix; cần thử giữ nguyên word inputs/beam1 và chỉ đổi start token để đo tác động.",
        "RGB -> resize384x384, mean/std0.5 theo processor config; native training dataset cũng convert RGB rồi gọi processor. Adapter không có app-level HSV background/ink filtering của demo; margins, word input distribution và decoding chưa được qualify đồng nhất upstream. **Không tự sửa runtime/weights hay chạy lại trong báo cáo này.**", "",
        "## A/B/C controls", "", "| Nhánh | Đầu vào | Document Pass |", "|---|---|---:|",
        "| A FastOCR | Nguyên dòng | 40/100 |", "| B FastOCR | Mảnh từ cùng segmentation với C | 8/100 |", "| C TrOCR | Cùng mảnh như B | 0/100 |", "",
        "A→B đo tổng ảnh hưởng cropping/context/assembly và cách batching mới, không tách riêng được segmentation. B→C cố định mảnh ảnh nhưng đổi recognizer/preprocess/decoding. Không cộng các chênh lệch để suy phần trăm lỗi do từng nguyên nhân.", "",
        "![Thống kê](diagnostic_overview.png)", "", "## Thống kê toàn bộ inputs và outputs", "",
        "| Chỉ số | Giá trị | Diễn giải |", "|---|---:|---|",
        f"| Parent crops | {summary['parent_crops']} | Cùng thứ tự/geometry |",
        f"| Mảnh | {summary['segments']} | Không có boundary GT xác nhận từng mảnh là một từ |",
        f"| Parent có mảnh width/height >5 | {summary['parents_with_wide_segment']} | Geometry risk, không phải error count |",
        f"| Parent chỉ1 mảnh và aspect >5 | {summary['single_wide_parents']} | Rủi ro gom cả dòng |",
        f"| Parent có mảnh aspect <0,35 | {summary['parents_with_narrow_fragment']} | Có thể là digit/punctuation đúng hoặc cắt vụn |",
        f"| Parent height >width | {summary['vertical_parents']} | Có cả mẩu rất nhỏ; không đồng nghĩa141 dòng chữ xoay |",
        f"| Blank parents /0mảnh | {summary['blank_parents']} | Model không được gọi cho mảnh không tồn tại |",
        f"| B/C exact raw word-output agreement | {summary['same_word_decoder_agreements']}/{summary['segments']} ({summary['same_word_decoder_agreements']/summary['segments']:.2%}) | Agreement, **không phải accuracy** |",
        f"| TrOCR word output rỗng | {summary['empty_trocr_segments']} | Không giải thích lỗi bằng lost-output dropout |",
        f"| TrOCR word truncation flag | {summary['truncated_trocr_segments']} | Theo saved EOS checks, không phải đánh giá transcription completeness |", "",
        "Không có line/word transcription GT nên không báo recognition CER/WER, true word accuracy hay segmentation precision/recall. Field CER trong benchmark nếu có là KIE field metric, không thay thế recognition CER.", "",
        "## F1/NEM theo12 trường", "", "![F1 và NEM](kie_f1_nem.png)", "",
        "Mỗi ô dưới là **F1 / NEM (%)**; CSV còn giữ precision, recall, VAI-style ACC và coverage. Target PoC F1/precision/recall≥85%, stretch≥90%; NEM≥75%. VAI-style ACC chỉ tham chiếu, chưa xác nhận điều kiện đầu vào datasheet. Không lấy F1/NEM để tự kết luận đạt mọi target.", "",
        "| Trường | A nguyên dòng | B cùng mảnh | C TrOCR |", "|---|---:|---:|---:|"]
    for field in metrics[metrics.model=="fastocr_control"].field_name:
        cells=[]
        for run in RUNS:
            row=metrics[(metrics.model==run)&(metrics.field_name==field)].iloc[0]
            cells.append(f"{100*row.f1:.2f} / {100*row.nem:.2f}")
        lines.append(f"| {TITLES[field]} ({field}) | "+" | ".join(cells)+" |")
    lines += ["", "## Review trực quan30 crop", "",
        "Đã thực sự xem30 final evidence cards bằng image-view tool. Chọn mẫu risk-stratified có chủ đích, không ngẫu nhiên, không dùng để ước lượng tỉ lệ lỗi toàn bộ. Nhóm nhiều rủi ro ưu tiên và cap3 crops/document. Một số candidate ban đầu không có writing/stamp đúng vùng; đã thay bằng crop mã/ngày viết tay/tên bị dấu đè, lưu initial_selection_before_visual_refinement.json để audit. Review không sửa GT, không tạo word transcription gold.", "",
        "Các kết luận dựa vào hình ảnh, không lấy output FastOCR làm GT. `uncertain` được giữ khi ảnh không đủ đọc. Một crop có nhiều tags; không cộng counts như các nhóm loại trừ nhau.", "",
        "### Các bằng chứng tiêu biểu", "",
        "- [case02](evidence/case_02.png): cả dòng văn bản thành1 mảnh; C chỉ ra Trước.",
        "- [case12](evidence/case_12.png), [case15](evidence/case_15.png): ranh giới từ hợp lý nhưng C vẫn sai QUẢN/NIÊM, TY/CỔ; không thể đổ hết cho splitter.",
        "- [case14](evidence/case_14.png): 11→1|1; C đọc đúng từng digit nhưng assembly sinh1 1.",
        "- [case23](evidence/case_23.png): C đọc đúng07 viết tay trong khi B raOF; không phải mọi handwritten word đều thất bại.",
        "- [case25](evidence/case_25.png): chữ số viết tay chạm chữ in, nhiều từ gom chung, C làm mất ngày.",
        "- [case27](evidence/case_27.png): dấu/nét ký giao cắt Nguyễn Xuân, gom chung rồi C ra kiên; Phúc ở mảnh riêng được đọc đúng.",
        "- [case19](evidence/case_19.png),21,22: blank inputs trả rỗng là hợp lý; [case20](evidence/case_20.png) giữ uncertain vì chỉ là fragment xoay.", "",
        "| Case | Nhóm chọn | Quan sát |", "|---|---|---|"]
    lookup={r['case_id']:r for r in reviews}
    for case in cases:
        lines.append(f"| [{case['case_id']}](evidence/{case['case_id']}.png) | {case['selection_stratum']} | {lookup[case['case_id']]['note']} |")
    lines += ["", "## Next actions, chưa thực thi", "",
        "1. **P0: qualify decoder trước** trên một bộ word crops nhỏ đã xem ảnh: chỉ đổi decoder_start2→0, giữ beam1 và mọi input khác; lưu output riêng, không overwrite lượt cũ. Chỉ sau đó thử beam1/4, ngram0/3, token cap32/64 theo từng biến.",
        "2. **P1: tách đánh giá segmentation khỏi OCR:** cần word-boundary/transcription annotations riêng để đo; kiểm tra crop gom dòng, số bị cắt rời, punctuation-only và orientation. Không giảm gap threshold toàn cục chỉ để score đẹp hơn vì có thể tăng cắt vụn.",
        "3. **P1: cải thiện assembly dưới ablation có kiểm soát:** giữ dấu câu, digit/code continuity bằng cơ chế hình học đã khai báo; không sửa theo GT hay tên file. Phải đối chiếu A/B và regression ở ngày/mã.",
        "4. **P2: chỉ cân nhắc domain fine-tuning** sau khi xác minh đúng decoding/preprocess. Cần cả printed-uppercase, số/mã/ngày, dấu đè và mixed handwriting, với holdout tách document/source. Không fine-tune trên100 document đang dùng để báo benchmark rồi coi đó là test độc lập.", "",
        "## Notebook và dữ liệu", "",
        "- [Notebook phân tích đã execute offline](trocr_error_analysis.ipynb): summary, audit decoding, F1/NEM, bộ lọc crops/words và hàm show_case để xem ảnh + bảng từng mảnh.",
        "- parent_crop_diagnostics.csv / word_diagnostics.csv:6.619 parents và52.542 mảnh.",
        "- visual_reviews.csv / image_view_ledger.csv:30 reviews có evidence hashes. Timestamp ledger là thời điểm ghi nhận, không bịa timestamp chính xác của tool-view.",
        "- decoding_audit.json / source_reference/:fine-tuning và config evidence.",
        "- integrity_validation.json:kiểm tra lại hashes input/GT và input parity; không inference.", ""]
    report_text="\n".join(lines)
    supplement=output/"supplemental_printed8_case.md"
    if supplement.exists():
        report_text=report_text.replace("## Next actions, chưa thực thi",supplement.read_text()+"\n## Next actions, chưa thực thi",1)
    (output/"REPORT.md").write_text(report_text)
    return tags


def make_notebook(output):
    import nbformat as nbf
    import textwrap
    cells=[]
    def md(text): cells.append(nbf.v4.new_markdown_cell(text))
    def code(text): cells.append(nbf.v4.new_code_cell(textwrap.dedent(text).strip()))
    md("# TrOCR: segmentation và OCR error analysis\n\n**Offline only:** không import/load/run OCR model, không train hay sửa GT. A=FastOCR dòng; B=FastOCR cùng mảnh; C=TrOCR. Đọc REPORT.md trước. Không có word GT nên không báo recognition CER/WER.")
    code('''
        from pathlib import Path
        import json
        import pandas as pd
        import matplotlib.pyplot as plt
        from IPython.display import display, Image, Markdown
        ANALYSIS = Path.cwd()
        if not (ANALYSIS / "summary.json").is_file():
            candidates = [p / "ocr-collab/artifacts/trocr_error_analysis_20261019" for p in [Path.cwd(), *Path.cwd().parents]]
            ANALYSIS = next(p for p in candidates if (p / "summary.json").is_file())
        summary = json.loads((ANALYSIS / "summary.json").read_text())
        audit = json.loads((ANALYSIS / "decoding_audit.json").read_text())
        parents = pd.read_csv(ANALYSIS / "parent_crop_diagnostics.csv", keep_default_na=False)
        words = pd.read_csv(ANALYSIS / "word_diagnostics.csv", keep_default_na=False)
        metrics = pd.read_csv(ANALYSIS / "field_metrics.csv")
        cases = json.loads((ANALYSIS / "selected_cases.json").read_text())
        reviews = pd.read_csv(ANALYSIS / "visual_reviews.csv")
        assert len(parents)==6619 and len(words)==52542 and len(cases)==30
        display(pd.Series({k:v for k,v in summary.items() if not isinstance(v,(dict,list))}).to_frame("value"))
    ''')
    md("## Checkpoint có fine-tune không?\nCó, theo README và training notebook tại đúng revision: Microsoft TrOCR base-handwritten → HANDS-VNOnDB word handwriting,10 epochs. Không local fine-tuning. Số94,42% word accuracy /2,30%CER là tác giả công bố, không phải kết quả của100PDF này.")
    code('''
        display(pd.Series({k:audit[k] for k in ["checkpoint_repo","revision","base_model","training_dataset","upstream_epochs","local_finetuning_performed","checkpoint_sha256"]}).to_frame("evidence"))
    ''')
    md("## P0: decoding chưa khớp upstream\nConfig top-level start0, saved generation_config start2; local adapter dùng generation config mà không override start. Toàn bộ token IDs lưu có prefix[2,0,...]. Source test dùng start0/beam4/max32/ngram3. Đây là discrepancy đã xác nhận, **chưa đo causal effect**. Không có inference trong notebook này.")
    code('''
        display(pd.DataFrame({"benchmark":audit["benchmark"], "upstream_test":audit["upstream_test"]}))
        display(words[["starts_with_token","second_token"]].value_counts().rename("segments"))
    ''')
    md("## Geometry và KIE\nCác ngưỡng aspect chỉ là risk flags. Decoder agreement không phải accuracy. A→B là tổng segmentation/context/assembly/batching; B→C thay recognizer/preprocess/decoding trên cùng mảnh.")
    code('''
        display(Image(filename=str(ANALYSIS / "diagnostic_overview.png")))
        display(Image(filename=str(ANALYSIS / "kie_f1_nem.png")))
        display(metrics.pivot(index="field_name", columns="model", values=["f1","nem"]).round(4))
    ''')
    md("## Review30 crop có chủ đích\nKhông dùng30 mẫu để ước lượng tỉ lệ lỗi dataset. Có blank/nonword và uncertain; các tags không loại trừ nhau. Đây là qualitative annotation trong report, không sửa benchmark GT.")
    code('''
        display(reviews[["case_id","selection_stratum","segmentation_issue","recognition_issue","note"]])
        display(reviews["tags"].str.split(";").explode().value_counts().to_frame("reviewed_cases_not_prevalence"))
    ''')
    code('''
        def show_case(case_id):
            case = next(c for c in cases if c["case_id"] == case_id)
            review = reviews[reviews.case_id == case_id].iloc[0]
            display(Markdown("### " + case_id + "\\n" + review["note"]))
            display(Image(filename=str(ANALYSIS / "evidence" / (case_id + ".png"))))
            display(pd.Series({key:case[key] for key in ["document_id","page_index_0based","crop_index","fastocr_line_text","fastocr_word_text","trocr_text"]}).to_frame("saved_output"))
            selected = words[(words.document_id==case["document_id"]) & (words.page_index_0based==case["page_index_0based"]) & (words.crop_index==case["crop_index"])]
            display(selected[["word_index","width","height","aspect_ratio","fastocr_text","trocr_text","trocr_truncated"]])
        # Đổi ID00..29 để xem các case khác, không chạy OCR lại.
        show_case("case_12")
    ''')
    code('''
        # Segmentation/assembly: cùng digit đúng nhưng join thành1 1.
        show_case("case_14")
        # Mixed handwriting và undermerge.
        show_case("case_25")
        # Dấu đè tên in: gom Nguyễn Xuân, Phúc vẫn đúng.
        show_case("case_27")
    ''')
    if (output/"supplemental_printed8_case.json").exists():
        md("## Bổ sung: tháng8 in nghiêng, file4977\nAgy đã trực tiếp xem ảnh: chữ `tháng` in đứng, số **8 in nghiêng** sát ngay sau chữ, không phải08 hay viết tay. Hình chiếu ngang chồng lấn nhưng vẫn còn khe trắng2D khoảng1pixel, **không khẳng định mực chạm nhau**. Ví dụ bổ sung, không thay đổi thống kê30crop ban đầu. A/B đều FastOCR Seq2Seq cùng weights baseline; C là TrOCR.")
        code('''
            extra = json.loads((ANALYSIS / "supplemental_printed8_case.json").read_text())
            display(Image(filename=str(ANALYSIS / extra["evidence_path"])))
            display(pd.DataFrame({
                "OCR saved": {"A FastOCR line": extra["fastocr_line_text"], "B FastOCR words": extra["fastocr_word_text"], "C TrOCR words": extra["trocr_text"]},
                "documentDate saved": dict(zip(["A FastOCR line", "B FastOCR words", "C TrOCR words"], [extra["saved_documentDate"][k] for k in "ABC"]))
            }))
            extra_words = words[(words.document_id==extra["document_id"]) & (words.page_index_0based==extra["physical_page_0based"]) & (words.crop_index==extra["crop_index"])]
            display(extra_words[["word_index","width","height","fastocr_text","trocr_text"]])
        ''')
        md("**A** nhầm tháng8→1; **B** giữ tháng8 nhưng ngày07→77; **C** bỏ8 khỏi tháng8, bỏ07 và sai năm. Không dùng ví dụ này để tách định lượng tác động segmentation/domain/decoding. Không inference lại hay sửa GT. [Chi tiết bổ sung](supplemental_printed8_case.md).")
    md("## Bộ lọc toàn bộ crop/word diagnostics\nOutput strings là predictions, không phải transcription GT. Đổi điều kiện dưới để khám phá các nhóm.")
    code('''
        display(parents[parents.single_wide_segment].head(20)[["document_id","page_index_0based","crop_index","segments","fastocr_line_text","trocr_text"]])
        # Non-exclusive geometry risk groups; không gọi là error rates.
        display(words.groupby(pd.cut(words.aspect_ratio,[0,.35,5,float("inf")]))["exact_decoder_agreement"].agg(["count","mean"]))
    ''')
    md("## Next actions\n1. Qualify start2 vs0 trên cùng words, giữ beam1 để isolate1biến.\n2. Sau đó thử beam1/4, ngram0/3, max32/64 riêng từng biến.\n3. Boundary/transcription audit riêng để đo splitter, giữ digit/punctuation continuity.\n4. Fine-tune domain chỉ sau parity và có holdout tách document/source. Các bước này là đề xuất, chưa thực thi.\n\nCác con số hiện tại chỉ áp dụng cho config đã đo, không kết luận TrOCR chưa fine-tune hoặc mô hình intrinsically0%accuracy.")
    nb=nbf.v4.new_notebook(cells=cells,metadata=dict(kernelspec=dict(display_name="Python 3",language="python",name="python3")))
    path=output/"trocr_error_analysis.ipynb"
    nbf.write(nb,path)
    from nbclient import NotebookClient
    NotebookClient(nb,timeout=120,kernel_name="python3",resources={"metadata":{"path":str(output)}}).execute()
    nbf.validate(nb)
    nbf.write(nb,path)
    if any(out.output_type=="error" for cell in nb.cells if cell.cell_type=="code" for out in cell.outputs):
        raise ValueError("Notebook execution failed")
    return len(nb.cells)


def verify_inputs(output):
    import hashlib
    import numpy as np
    from PIL import Image
    rows=read(output/"input_integrity_before.json")
    changed=[r["path"] for r in rows if sha256(r["path"])!=r["sha256"]]
    if changed:
        raise ValueError(f"Protected source/GT modified: {changed}")
    mapping=read(EXPERIMENT/"word_crop_cache_manifest.json")
    from scripts.analyze_trocr_saved_errors import CACHE
    for row in mapping["parents"]:
        path=CACHE/row["document_id"]/f"page_{row['physical_page_index_0based']+1}"/"crops"/f"{row['detection_index']}.png"
        with Image.open(path) as image:
            digest=hashlib.sha256(np.asarray(image.convert("RGB")).tobytes()).hexdigest()
        if digest!=row["parent_rgb_sha256"]:
            raise ValueError("Parent RGB hash differs from frozen mapping")
    result=dict(status="passed",protected_files=len(rows),modified_inputs=[],gt_and_sources_unchanged=True,
        parent_rgb_hashes_verified=len(mapping["parents"]),same_word_mapping_verified=True,no_model_inference=True)
    write(output/"integrity_validation.json",result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    output=args.output.resolve()
    audit=build_audit(output)
    cases,reviews=finalize_reviews(output)
    summary=read(output/"summary.json")
    summary["visual_review"]="30_selected_cases_viewed_and_reviewed_not_full_dataset"
    write(output/"summary.json",summary)
    make_plots(output)
    tags=make_report(output,summary,audit,cases,reviews)
    cells=make_notebook(output)
    validation=verify_inputs(output)
    write(output/"manifest.json",dict(status="completed",mode="offline_saved_output_visual_error_analysis",
        parent_crops=6619,segments=52542,reviewed_visual_cases=30,notebook_executed=True,notebook_cells=cells,
        supplemental_visual_cases=int((output/"supplemental_printed8_case.json").exists()),
        no_ocr_inference=True,no_finetuning=True,review_tags=dict(tags),validation=validation,
        caveat="Not segmentation error prevalence, not recognition CER/WER; decoding config differs from upstream."))
    print(output/"REPORT.md")
    print(output/"trocr_error_analysis.ipynb")


if __name__=="__main__":
    main()
