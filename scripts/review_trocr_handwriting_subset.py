"""Prepare/review saved TrOCR crops: 30 handwriting + 5 printed, no inference."""
import argparse
import csv
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.analyze_trocr_saved_errors import read,write,render_case,EXPERIMENT,RUNS

ANALYSIS=ROOT/"ocr-collab/artifacts/trocr_error_analysis_20261019"


def normalized(text):
    return re.sub(r"[^\w]","",text.casefold())


def records_for_case(case):
    records=[]
    for run in RUNS:
        path=EXPERIMENT/run/"cache"/case["document_id"]/f"page_{case['page_index_0based']+1}"/"results.json"
        data=read(path)
        index=next(i for i,row in enumerate(data["recognition"]) if row["crop_index"]==case["crop_index"])
        records.append(dict(recognition=data["recognition"][index],detail=data["recognition_details"][index] if data["recognition_details"] else None))
    return records


def prepare(output):
    from PIL import Image,ImageDraw
    from scripts.analyze_trocr_saved_errors import font
    import pandas as pd
    parents=pd.read_csv(ANALYSIS/"parent_crop_diagnostics.csv",keep_default_na=False).to_dict("records")
    predictions=[json.loads(line) for line in (EXPERIMENT/"fastocr_control/candidate_predictions.jsonl").read_text().splitlines()]
    candidates=[]
    for record in predictions:
        metadata=record["metadata"]
        writing=metadata["handwritten_fields"]["value"]
        page=metadata["document_start_page"]["value"]
        rows=[r for r in parents if r["document_id"]==record["document_id"] and r["page_index_0based"]==page]
        if not writing:
            continue
        if "code" in writing:
            target=normalized(record["prediction"]["code"])
            possibilities=[r for r in rows if r["fastocr_line_text"].casefold().startswith(("số","sổ","sô","só","so:")) and r["crop_index"]<25]
            if not possibilities:
                possibilities=rows[:15]
            case=max(possibilities,key=lambda r:SequenceMatcher(None,target,normalized(r["fastocr_line_text"])).ratio())
            field="code"
        else:
            possibilities=[r for r in rows if "ngày" in r["fastocr_line_text"].casefold() and r["crop_index"]<20]
            if not possibilities:
                continue
            case=possibilities[0]
            field="documentDate"
        candidates.append({**case,"case_id":f"candidate_{len(candidates):02d}","selection_stratum":"handwriting_candidate_unconfirmed", "target_field":field})
    output.mkdir(parents=True,exist_ok=False)
    write(output/"handwriting_candidates.json",candidates)
    for start in range(0,len(candidates),8):
        subset=candidates[start:start+8]
        sheet=Image.new("RGB",(2000,len(subset)*200),"white")
        draw=ImageDraw.Draw(sheet)
        for i,case in enumerate(subset):
            draw.text((12,i*200+4),f"{case['case_id']} | {case['document_id']} | page {case['page_index_0based']+1}, crop {case['crop_index']}",font=font(20),fill="black")
            with Image.open(case["parent_path"]) as source:
                image=source.convert("RGB");scale=min(3,1950/image.width,130/image.height)
                image=image.resize((max(1,round(image.width*scale)),max(1,round(image.height*scale))))
            sheet.paste(image,(12,i*200+38))
        sheet.save(output/f"candidate_sheet_{start//8:02d}.png")
    print(f"Prepared {len(candidates)} unconfirmed candidates for actual image inspection")


def render_final(output):
    selection=read(output/"selection.json")
    candidates={r["case_id"]:r for r in read(output/"handwriting_candidates.json")}
    import pandas as pd
    parents=pd.read_csv(ANALYSIS/"parent_crop_diagnostics.csv",keep_default_na=False).to_dict("records")
    cases=[]
    for item in selection:
        if "candidate_id" in item:
            case=candidates[item["candidate_id"]]
        else:
            case=next(r for r in parents if (r["document_id"],r["page_index_0based"],r["crop_index"]) ==
                      (item["document_id"],item["page_index_0based"],item["crop_index"]))
        cases.append({**case,**item,"case_id":f"review_{len(cases):02d}","selection_stratum":item["visual_condition"]})
    if len(cases)!=35 or len({r["document_id"] for r in cases})!=35:
        raise ValueError("Expected 35 crops from 35 distinct documents")
    if sum(r["visual_condition"]=="handwriting" for r in cases)!=30:
        raise ValueError("Expected 30 visually confirmed handwriting crops")
    if sum(r["visual_condition"]=="printed_only" for r in cases)!=5:
        raise ValueError("Expected 5 printed-only crops")
    evidence=output/"evidence"
    evidence.mkdir(exist_ok=False)
    for case in cases:
        render_case(case,*records_for_case(case),evidence/f"{case['case_id']}.png")
    write(output/"selected_cases.json",cases)
    print("Rendered 35 cards; final image review still required")


def finalize(output):
    from collections import Counter
    import hashlib
    import nbformat as nbf
    from nbclient import NotebookClient
    from scripts.check_cached_ocr_equivalence import sha256
    cases=read(output/"selected_cases.json")
    reviews=read(output/"visual_reviews.json")
    lookup={r["case_id"]:r for r in reviews}
    if len(cases)!=35 or len(lookup)!=35 or set(lookup)!={r["case_id"] for r in cases}:
        raise ValueError("Expected exactly 35 reviewed cases")
    if not all(r["condition_confirmed"] for r in reviews):
        raise ValueError("Unconfirmed image condition")
    handwritten=[r for r in cases if r["visual_condition"]=="handwriting"]
    if len(handwritten)!=30 or len({r["document_id"] for r in cases})!=35:
        raise ValueError("Expected 30 handwriting crops and 35 distinct documents")
    boundary=Counter(lookup[r["case_id"]]["handwritten_span_boundary"] for r in handwritten)
    outcomes=Counter(lookup[r["case_id"]]["trocr_handwritten_span"] for r in handwritten)
    rows=[]
    for case in cases:
        rows.append({**{k:case[k] for k in ("case_id","document_id","page_index_0based","crop_index","visual_condition","fastocr_line_text","fastocr_word_text","trocr_text")},**lookup[case["case_id"]],
            "evidence_sha256":sha256(output/"evidence"/(case["case_id"]+".png"))})
    with (output/"review_results.csv").open("w") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    protected=read(ANALYSIS/"input_integrity_before.json")
    changed=[r["path"] for r in protected if sha256(r["path"])!=r["sha256"]]
    if changed:
        raise ValueError(f"Protected inputs changed: {changed}")
    import numpy as np
    from PIL import Image
    for case in cases:
        records=records_for_case(case)
        b,c=[r["detail"]["metadata"] for r in records[1:]]
        if any(b[key]!=c[key] for key in ("parent_rgb_sha256","boxes","words")):
            raise ValueError("B/C image inputs differ")
        with Image.open(case["parent_path"]) as image:
            rgb=np.asarray(image.convert("RGB"))
        if hashlib.sha256(rgb.tobytes()).hexdigest()!=c["parent_rgb_sha256"]:
            raise ValueError("Parent image changed")
    summary=dict(status="completed",reviewed_crops=35,distinct_documents=35,handwriting_crops=30,printed_only_crops=5,
        handwritten_span_boundary=dict(boundary),trocr_handwritten_span=dict(outcomes),
        protected_files_unchanged=len(protected),parent_rgb_hashes_verified=35,same_word_inputs_verified=True,
        no_inference=True,no_gt_modifications=True,
        limitation="Purposeful qualitative sample, not transcription GT or dataset accuracy. Handwriting mostly digits within mixed printed/handwritten code/date crops.")
    write(output/"summary.json",summary)
    lines=["# TrOCR: review 30 crop có chữ viết tay + 5 crop chỉ chữ in", "",
        "## Kết quả", "",
        "Đã xem trực tiếp 35 final evidence cards, từ **35 file khác nhau**: **30 crop có nét viết tay nhìn thấy**, **5 crop chỉ chữ in**. Không chỉ dựa vào metadata của file. Phần viết tay chủ yếu là số mã/ngày được điền trên mẫu in, không phải 30 dòng văn xuôi viết tay hoàn toàn.", "",
        f"- Ranh giới phần viết tay: **{boundary['isolated']} crop giữ riêng nguyên cụm**, **{boundary['merged']} crop gom với chữ in**, **{boundary['mixed']} crop hỗn hợp**.",
        f"- TrOCR giữ đúng phần số viết tay qua đối chiếu ảnh ở **{outcomes['visually_preserved']}/30 crop**; **{outcomes['not_preserved']}/30 không giữ đúng**, **{outcomes['uncertain']}/30 chưa đủ rõ để kết luận**.",
        "- Đây là nhận xét định tính cho phần viết tay được xem, **không phải word accuracy/CER/WER**, không chấm đúng toàn bộ dòng và không suy rộng tỉ lệ lỗi dataset. Không lấy FastOCR hay tên file làm transcription GT.", "",
        "## Các phát hiện chính", "",
        "1. TrOCR có thể đọc đúng số viết tay khi giữ riêng cụm, ví dụ `07`, `1321`, `2271`, `3269`; có trường hợp FastOCR cùng mảnh đọc sai. Nhưng phần mã in bên cạnh vẫn có thể sai.",
        "2. Khi số viết tay dính nhãn `Số` hoặc mã in thành một mảnh, C thường rút cả cụm còn một từ như `sườn`, làm mất số. Không thể quy riêng lỗi này cho model mà bỏ qua segmentation.",
        "3. Tách riêng số chưa đảm bảo đọc đúng: `156 → 150`, `2472 → 24782`; đây là lỗi phía recognition/config hiện tại trên mảnh giữ nguyên số.",
        "4. Năm crop chỉ chữ in cũng có lỗi: từ in hoa/dấu, mã bị đổi thành từ, `2026 → 2020`. Chữ viết tay không phải lời giải thích duy nhất.",
        "5. Crop `review_13` giữ uncertain vì số viết tay khó phân biệt; không dùng tên file để ép transcription.", "",
        "## Cấu hình và giới hạn", "",
        "A = FastOCR nguyên dòng; B = FastOCR trên cùng mảnh với C; C = TrOCR. Cùng output benchmark đã lưu, không inference lại. Checkpoint đã được tác giả fine-tune VNOnDB từng từ, chưa fine-tune local trên dữ liệu hành chính.",
        "Lượt benchmark dùng decoder start token2/beam1, notebook upstream dùng token0/beam4. Có lệch decoding đã xác nhận nhưng **chưa đo ảnh hưởng riêng**. Kết quả này chỉ áp dụng cho cấu hình đã chạy, không kết luận năng lực tối đa của checkpoint.",
        "Mẫu chọn có chủ đích từ fixed crop cache; 29 crop viết tay là dòng mã, 1 là dòng ngày. Không đại diện mọi kiểu chữ viết tay, câu dài hay tài liệu toàn bộ viết tay. `printed_only` xác nhận ở crop, không suy ra mọi trang của file đều không có viết tay.", "",
        "## Chi tiết 35 crop", "", "A/B/C đầy đủ và metadata nằm trong [review_results.csv](review_results.csv). Mỗi ảnh có parent, box mảnh và output B/C từng mảnh.", "",
        "| Crop | Nhóm | Quan sát trực tiếp |", "|---|---|---|"]
    for case in cases:
        review=lookup[case["case_id"]]
        lines.append(f"| [{case['case_id']}](evidence/{case['case_id']}.png) | {case['visual_condition']} | {review['note']} |")
    lines.extend(["", "## Notebook và kiểm tra", "",
        "[Notebook đã execute offline](review_30_handwriting_5_printed.ipynb), có bảng 35 crop và hàm xem từng ảnh/output. Không load OCR model.",
        f"Đã xác nhận {len(protected)} file nguồn/GT/results được bảo vệ không đổi, hashes RGB của35 parent crops và parity word inputs B/C. Báo cáo cũ30 mẫu hỗn hợp vẫn được giữ nguyên.", ""])
    (output/"REPORT.md").write_text("\n".join(lines))
    cells=[nbf.v4.new_markdown_cell("# Review30 crop viết tay +5 crop chữ in\n\n35 file khác nhau. Phân tích offline output đã lưu, không inference. Xem REPORT.md để đọc giới hạn; số đúng phần viết tay không đồng nghĩa đúng toàn dòng."),
        nbf.v4.new_code_cell("from pathlib import Path\nimport json\nimport pandas as pd\nfrom IPython.display import display, Image, Markdown\nBASE=Path.cwd()\nif not (BASE/'review_results.csv').exists():\n    BASE=next(p/'ocr-collab/artifacts/trocr_handwriting_review_30plus5_20261019' for p in [Path.cwd(),*Path.cwd().parents] if (p/'ocr-collab/artifacts/trocr_handwriting_review_30plus5_20261019/review_results.csv').exists())\nsummary=json.loads((BASE/'summary.json').read_text())\nresults=pd.read_csv(BASE/'review_results.csv',keep_default_na=False)\ndisplay(summary)\nassert len(results)==35 and results.document_id.nunique()==35\ndisplay(results[['case_id','visual_condition','handwritten_span_boundary','trocr_handwritten_span','note']])"),
        nbf.v4.new_markdown_cell("## Xem ảnh và output A/B/C\nĐổi case_id từ review_00 đến review_34. review_00..29 có viết tay; review_30..34 chỉ chữ in. Không dùng FastOCR như GT."),
        nbf.v4.new_code_cell("def show_case(case_id):\n    row=results[results.case_id==case_id].iloc[0]\n    display(Markdown('### '+case_id+'\\n'+row['note']))\n    display(Image(filename=str(BASE/'evidence'/(case_id+'.png'))))\n    display(row[['document_id','page_index_0based','crop_index','fastocr_line_text','fastocr_word_text','trocr_text']].to_frame('saved_output'))\nshow_case('review_04')"),
        nbf.v4.new_code_cell("# Số tách riêng nhưng đọc sai; sau đó đối chứng chỉ chữ in.\nshow_case('review_11')\nshow_case('review_34')"),
        nbf.v4.new_markdown_cell("## Giới hạn và bước tiếp theo\nMẫu chủ đích, chủ yếu chữ số viết tay trong mẫu in; không có transcription GT và không tính CER/WER. Decoder benchmark start2/beam1 khác upstream start0/beam4; cần đối chứng từng biến trên cùng input sau khi được duyệt, chưa chạy trong notebook này.")]
    notebook=nbf.v4.new_notebook(cells=cells,metadata=dict(kernelspec=dict(display_name="Python 3",language="python",name="python3")))
    NotebookClient(notebook,timeout=120,kernel_name="python3",resources={"metadata":{"path":str(output)}}).execute()
    nbf.validate(notebook)
    nbf.write(notebook,output/"review_30_handwriting_5_printed.ipynb")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--stage",choices=("candidates","render","finalize"),required=True)
    args=parser.parse_args()
    {"candidates":prepare,"render":render_final,"finalize":finalize}[args.stage](args.output.resolve())


if __name__=="__main__":
    main()
