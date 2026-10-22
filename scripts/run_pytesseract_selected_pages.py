"""Full PSM 6/7/13 benchmark with ONLY selected-page OCR/blocks supplied to KIE."""
import argparse
import copy
import csv
import json
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"ocr-collab"))
sys.path.insert(0,str(ROOT/"ocr-collab/experiments"))
from scripts.check_cached_ocr_equivalence import sha256,dump,write_jsonl,load_cached_page,flat_prediction,diagnostic_record,selected_pages,validate_source

SOURCE=ROOT/"ocr-collab/artifacts/evidence_full_inference_title_footnote_fix_20261015"
CACHE=ROOT/"ocr-collab/artifacts/cached_ocr_equivalence_20261015"
SAVED={
    "fastocr_selected":ROOT/"ocr-collab/artifacts/recognizer_ab_trocr_20261015/fastocr_control",
    "nom_raw_selected":ROOT/"ocr-collab/artifacts/recognizer_ab_nom_20261016/nom_tesseract_raw",
}
MODE="selected_boundary_pages_only_no_unselected_ocr_or_blocks"


def read(path):
    return json.loads(Path(path).read_text())


def selected_only_pages(page_count,selected_blocks):
    """Keep physical indices without ever populating unselected-page text/blocks."""
    if any(type(i) is not int or not 0<=i<page_count for i in selected_blocks):
        raise ValueError("Invalid selected physical page index")
    pages=[[] for _ in range(page_count)]
    for index,blocks in selected_blocks.items():
        pages[index]=blocks
    return pages


def verify_selected_evidence(evidence,selected):
    for field,item in evidence.items():
        # Evidence may be absent or use page=None for default enums.
        for entry in item if isinstance(item,list) else [item]:
            if isinstance(entry,dict) and entry.get("page") is not None:
                if entry["page"]-1 not in selected:
                    raise ValueError(f"Evidence from unselected page: {field}: {entry}")


def pipeline_for(conf):
    from module.pipeline.document_pipeline import DocumentPipeline
    from module.pipeline.config import PipelineConfig
    from module.layout.pp_doclayout import PPDocLayoutBackend
    return DocumentPipeline(SimpleNamespace(label_schema=PPDocLayoutBackend.label_schema),
        SimpleNamespace(drop_score=.5),None,PipelineConfig.from_conf(conf))


def provenance():
    conf,_=validate_source(SOURCE)
    files=[SOURCE/"manifest.json",SOURCE/"pipeline_config.json",SOURCE/"predictions.jsonl",CACHE/"manifest.json"]
    files.extend(sorted((ROOT/"data/benchmark_demo/clean").glob("*.json")))
    files.extend(sorted((CACHE/"cache").glob("*/selection.json")))
    files.extend(sorted((CACHE/"cache").glob("*/page_*/input.json")))
    files.extend(sorted((CACHE/"cache").glob("*/page_*/crop_manifest.json")))
    files.extend(sorted((ROOT/"module/extract").rglob("*.py")))
    files.extend(sorted((ROOT/"module/pipeline").rglob("*.py")))
    files.extend(sorted((ROOT/"module/ocr/recognizers").glob("*.py")))
    files.append(Path(__file__).resolve())
    return conf,{str(p):sha256(p) for p in files}


def run_cohort(root,name,documents,config=None,saved=None):
    import benchmark as b
    import numpy as np
    from PIL import Image
    from module.extract.vbhc_rules import extract_vbhc
    from module.pipeline.document_pipeline import _PreparedPage
    from module.pipeline.ocr_page import finish_ocr_page
    from module.ocr.recognizers import create_recognizer
    from replay_all_v3 import _original_page_sizes

    folder=root/name
    conf,hashes=provenance()
    cases={c.document_id:c for c in b.load_cases(b.DEFAULT_CLEAN_DIR,b.DEFAULT_DATA_ROOT)}
    records=[json.loads(line) for line in (SOURCE/"predictions.jsonl").read_text().splitlines()]
    if documents is not None:
        records=[r for r in records if r["document_id"] in documents]
        if {r["document_id"] for r in records}!=set(documents):
            raise ValueError("Missing pilot documents")
    source_inputs={}
    for record in records:
        doc=record["document_id"]
        selection=read(CACHE/"cache"/doc/"selection.json")
        metadata=read(cases[doc].json_path)["metadata"]
        if selected_pages(metadata,record["page_count"])!=selection["selected_physical_pages_0based"]:
            raise ValueError("Current GT page selection differs from fixed cache")
        source_inputs[doc]=selection["selected_physical_pages_0based"]
        if saved:
            for page in source_inputs[doc]:
                path=saved/"cache"/doc/f"page_{page+1}"/"results.json"
                hashes[str(path)]=sha256(path)
    if documents is None:
        crop_count=sum(len(read(CACHE/"cache"/doc/f"page_{page+1}"/"crop_manifest.json")) for doc,pages in source_inputs.items() for page in pages)
        if (len(records),sum(map(len,source_inputs.values())),crop_count)!=(100,183,6619):
            raise ValueError("Full runs require the frozen 100 documents / 183 pages / 6619 crops")
    # Hash the pinned assets too, before a completed cohort or resume can be accepted.
    if config:
        model=ROOT/config["model_dir"]
        hashes[str(model/"download_manifest.json")]=sha256(model/"download_manifest.json")
        for relative,info in read(model/"download_manifest.json")["artifacts"].items():
            if relative.startswith(("runtime/","tessdata/")):
                path=model/relative
                if sha256(path)!=info["sha256"]:
                    raise ValueError(f"Pinned model asset changed: {relative}")
                hashes[str(path)]=info["sha256"]
    fingerprint=dict(mode=MODE,documents=[r["document_id"] for r in records],config=config,
        saved=str(saved) if saved else None,selected_pages=source_inputs,input_sha256=hashes,metric_version=b.METRIC_VERSION)
    folder.mkdir(parents=True,exist_ok=True)
    fp=folder/"run_fingerprint.json"
    if fp.exists():
        if read(fp)!=fingerprint:
            raise ValueError(f"Refusing stale/mismatched resume: {folder}")
        if (folder/"manifest.json").exists():
            print(f"SKIP completed {name}",flush=True)
            return folder
    elif any(folder.iterdir()):
        raise ValueError("Nonempty untracked cohort folder")
    dump(fp,fingerprint)
    dump(folder/"pipeline_config.json",{**conf,"benchmark_scope":MODE})
    dump(folder/"recognizer_config.json",config or dict(backend="saved_blocks_replay",source=str(saved)))
    snapshots=folder/"source_snapshot"
    snapshots.mkdir(exist_ok=True)
    for path in [Path(__file__),ROOT/"module/extract/vbhc_rules.py",ROOT/"module/ocr/recognizers/pytesseract_direct.py"]:
        shutil.copyfile(path,snapshots/path.name)
    pipeline=pipeline_for(conf) if config else None
    recognizer=create_recognizer(config) if config else None
    (folder/"checkpoints").mkdir(exist_ok=True)
    results,timing=[],[]
    try:
        for position,record in enumerate(records,1):
            doc=record["document_id"]
            checkpoint=folder/"checkpoints"/f"{doc}.json"
            if checkpoint.exists():
                saved_cp=read(checkpoint)
                results.append(saved_cp["prediction_record"])
                timing.append(saved_cp["timing"])
                print(f"[{name} {position}/{len(records)}] resumed {doc}",flush=True)
                continue
            started=time.perf_counter()
            selected=source_inputs[doc]
            source_trace=read(record["trace_path"])
            sizes=_original_page_sizes(cases[doc].pdf_path,record["page_count"])
            processed=[(page["width"],page["height"]) for page in source_trace["pages"]]
            offsets=[page["crop_offset"] for page in read(SOURCE/"pipeline_outputs"/doc/"output.json")["pages"]]
            original_kwargs=dict(original_page_sizes=sizes,processed_page_sizes=processed,crop_offsets=offsets,
                geometry_reliable=source_trace["extraction"]["geometry_reliable"])
            evidence_dir=folder/"evidence"/doc
            evidence_dir.mkdir(parents=True,exist_ok=True)
            blocks_by_page,trace_pages={},[]
            images,preps,all_crops={}, {}, []
            for page in selected:
                page_dir=CACHE/"cache"/doc/f"page_{page+1}"
                inp=read(page_dir/"input.json")
                if inp["page_index_0based"]!=page or inp["original_size"]!=list(sizes[page]):
                    raise ValueError("Physical page/geometry mismatch")
                if sha256(inp["image_path"])!=inp["image_sha256"]:
                    raise ValueError("Selected page image changed")
                shutil.copyfile(inp["image_path"],evidence_dir/f"page_{page+1}.png")
                if config:
                    prep,crops,_=load_cached_page(page_dir,dict(page_index_0based=page))
                    preps[page]=(prep,len(all_crops),len(crops),inp)
                    all_crops.extend(crops)
                    images[page]=Image.open(inp["image_path"]).convert("RGB")
                else:
                    old=read(saved/"cache"/doc/f"page_{page+1}"/"results.json")
                    blocks_by_page[page]=old["candidate_blocks"]
                    trace_pages.append(dict(page=page+1,physical_page_index_0based=page,width=inp["processed_size"][0],
                        height=inp["processed_size"][1],image_url=str(evidence_dir/f"page_{page+1}.png"),
                        ocr_lines=old["candidate_ocr_lines"],layout_blocks=inp["layout_blocks"],blocks=old["candidate_blocks"]))
            rec_started=time.perf_counter()
            if config:
                recognition,_=recognizer(all_crops)
                rec_seconds=time.perf_counter()-rec_started
                details=recognizer.last_details
                for page in selected:
                    prep,start,count,inp=preps[page]
                    fresh=recognition[start:start+count]
                    lines=finish_ocr_page(prep,fresh,SimpleNamespace(drop_score=.5))
                    skeleton,tables=pipeline._build_table_skeleton(page,images[page],copy.deepcopy(inp["layout_blocks"]))
                    if tables:
                        raise ValueError("Unexpected tables enabled")
                    blocks_by_page[page]=pipeline._process_page_after_layout(page,_PreparedPage(images[page],None,None),skeleton,lines)
                    dest=folder/"cache"/doc/f"page_{page+1}"
                    dest.mkdir(parents=True,exist_ok=True)
                    dump(dest/"results.json",dict(physical_page_index_0based=page,source_page_cache=str(CACHE/"cache"/doc/f"page_{page+1}"),
                        recognition=[dict(crop_index=i,text=r[0],score=r[1]) for i,r in zip(prep.crop_indices,fresh)],
                        recognition_details=details[start:start+count],candidate_ocr_lines=lines,candidate_blocks=blocks_by_page[page]))
                    trace_pages.append(dict(page=page+1,physical_page_index_0based=page,width=processed[page][0],height=processed[page][1],
                        image_url=str(evidence_dir/f"page_{page+1}.png"),ocr_lines=lines,layout_blocks=inp["layout_blocks"],blocks=blocks_by_page[page]))
            else:
                rec_seconds=0.0
                details=[]
            pages=selected_only_pages(record["page_count"],blocks_by_page)
            assert all(not blocks for i,blocks in enumerate(pages) if i not in selected)
            extracted,debug=extract_vbhc(pages,**original_kwargs)
            fields=flat_prediction(extracted,record["prediction"])
            evidence=debug.get("evidence",{})
            verify_selected_evidence(evidence,selected)
            for items in evidence.values():
                for entry in items if isinstance(items,list) else [items]:
                    if isinstance(entry,dict) and entry.get("page") is not None:
                        entry["image_path"]=str(evidence_dir/f"page_{entry['page']}.png")
            trace_path=evidence_dir/"trace.json"
            dump(trace_path,dict(version=2,document_id=doc,source_filename=Path(record["pdf_path"]).name,pdf_path=record["pdf_path"],
                mode=MODE,pages=trace_pages,selected_physical_pages_0based=selected,unselected_pages_have_no_ocr_or_blocks=True,
                markdown="\n\n".join(str(block.get("content","")) for page in selected for block in blocks_by_page[page]),
                extraction=dict(fields=fields,evidence=evidence,diagnostic=debug)))
            prediction=diagnostic_record(record,fields,evidence,trace_path)
            prediction.update(ground_truth=cases[doc].ground_truth,metadata=read(cases[doc].json_path)["metadata"],
                generation_mode=MODE,trace_path=str(trace_path),selected_physical_pages_0based=selected,
                selected_page_count=len(selected),unselected_page_ocr_used=False)
            stat=dict(document_id=doc,selected_pages=len(selected),crop_count=len(all_crops) if config else sum(len(read(CACHE/"cache"/doc/f"page_{p+1}"/"crop_manifest.json")) for p in selected),
                recognition_wall_seconds=rec_seconds if config else None,document_wall_seconds=time.perf_counter()-started,
                raw_cache_hits=sum(d["metadata"]["raw_cache_hit"] for d in details),
                original_call_seconds_sum=sum(d["metadata"]["original_call_seconds"] for d in details),
                timing_note="Recognition wall includes cache hits and IPC; sum of original calls overlaps across four threads and is not wall time")
            dump(checkpoint,dict(prediction_record=prediction,timing=stat))
            results.append(prediction);timing.append(stat)
            write_jsonl(folder/"predictions.jsonl",results)
            dump(folder/"timing.json",timing)
            print(f"[{name} {position}/{len(records)}] {doc}: {len(selected)} selected pages, {stat['crop_count']} crops, {rec_seconds:.3f}s recognition",flush=True)
            for image in images.values():
                image.close()
        b.write_evaluation(folder,results,dict(mode=MODE,full_inference=False,unselected_page_ocr_used=False))
        changed=[path for path,digest in hashes.items() if sha256(path)!=digest]
        if changed:
            raise ValueError(f"Source/GT changed during run: {changed}")
        dump(folder/"manifest.json",dict(status="completed",mode=MODE,documents=[r["document_id"] for r in results],
            selected_pages=sum(s["selected_pages"] for s in timing),crops=sum(s["crop_count"] for s in timing),
            source_inputs_unchanged=True,unselected_page_ocr_used=False,recognizer_config=config,
            timing_note="Measured adapter wall per document; not full PDF pipeline; prior cached pilot calls are not rerun",
            worker_runtime=getattr(recognizer,"worker_runtime",None)))
    finally:
        if recognizer and hasattr(recognizer,"close"):
            recognizer.close()
    return folder


def report(root):
    import pandas as pd
    names=("fastocr_selected","nom_raw_selected","pytesseract_psm6","pytesseract_psm7","pytesseract_psm13")
    frames=[]
    passes={}
    for name in names:
        frame=pd.read_csv(root/name/"metrics.csv")
        frame.insert(0,"model",name);frames.append(frame)
        passes[name]=read(root/name/"summary.json")["document_success_at_5"]["passed_documents"]
    metrics=pd.concat(frames,ignore_index=True)
    metrics.to_csv(root/"field_metrics.csv",index=False)
    timing=[]
    measured=[]
    for name in names[2:]:
        stats=read(root/name/"timing.json")
        item=dict(model=name,measurement="Actual adapter wall from this configuration; no timing-only pass",
            recognition_wall_seconds=sum(r["recognition_wall_seconds"] for r in stats),selected_pages=sum(r["selected_pages"] for r in stats),
            documents=len(stats),workers=4,omp_thread_limit=1,backend="CPU Tesseract 5.5.1 via pytesseract",precision="native Tesseract LSTM, not torch FP16/FP32",
            raw_cache_hits=sum(r["raw_cache_hits"] for r in stats))
        item["weighted_seconds_per_selected_page"]=item["recognition_wall_seconds"]/item["selected_pages"]
        item["average_seconds_per_document"]=item["recognition_wall_seconds"]/item["documents"]
        timing.append(item)
        measured.extend(dict(model=name,**r) for r in stats)
    dump(root/"recognition_timing_summary.json",timing)
    pd.DataFrame(measured).to_csv(root/"recognition_timing_per_document.csv",index=False)
    lines=["# Pytesseract tiếng Việt: chỉ 183 trang đầu/cuối đã chọn", "",
        "**Không spell correction. Không lấy OCR hoặc blocks từ trang không chọn.** KIE giữ chỉ số trang vật lý bằng các vị trí rỗng ở trang bị loại; ảnh và OCR trong evidence chỉ có trang được chọn. Không so trực tiếp điểm ở đây với artifact hybrid cũ.","",
        "## Cấu hình", "",
        "- `lang=vie`: traineddata tiếng Việt; `vi`/`vn` không phải model riêng có sẵn.",
        "- Tesseract5.5.1, tessdata_best vie cùng assets đã pin như lượt Nôm trước; pytesseract gọi trực tiếp, không qua Nôm và không sửa chữ.",
        "- OEM1=LSTM. PSM6=khối chữ; PSM7=một dòng; PSM13=raw line.",
        "- RGB + white border10px, không resize, threshold, deskew hay sửa dấu. Bốn tiến trình Tesseract song song qua thread pool; OMP_THREAD_LIMIT=1. Neutral assembly confidence1.0.",
        "- **Chạy full riêng cả PSM6/7/13**, mỗi cấu hình100PDF /183trang /6.619crop; không pilot để chọn lọc, không routing theo GT/tên file. Mọi kết quả cấu hình đều được công bố; thứ hạng trên cùng benchmark không phải ước lượng độc lập cho cấu hình tối ưu."]
    lines += ["", "## KIE cùng phạm vi trang", "",
        "FastOCR và Nôm raw được replay lại KIE từ selected-page blocks đã lưu, không chạy OCR lại. Pytesseract có nhận dạng mới; mọi nhánh đều không dùng trang còn lại.","",
        "| Nhánh | Document Pass /100 |", "|---|---:|"]
    lines.extend(f"| {name} | {passes[name]} |" for name in names)
    lines += ["", "Mỗi ô dưới: **F1 (precision, recall) / NEM / VAI-style ACC**, đơn vị%. ACC chuẩn hóa nội bộ chỉ tham chiếu; chưa đánh giá điều kiện đầu vào datasheet. Target PoC85(85,85)/75/không áp dụng; stretch90(90,90)/75/không áp dụng. Xem CSV cho hallucination và coverage; không kết luận đạt target chỉ từ F1.","",
        "| Field | FastOCR selected | Nôm raw selected | PSM6 | PSM7 | PSM13 |", "|---|---|---|---|---|---|"]
    for field in frames[0].field_name:
        cells=[]
        for name in names:
            row=metrics[(metrics.model==name)&(metrics.field_name==field)].iloc[0]
            cells.append(f"{100*row.f1:.2f} ({100*row.precision:.2f}, {100*row.recall:.2f}) / {100*row.nem:.2f} / {100*row.vai_acc:.2f}")
        lines.append("| "+field+" | "+" | ".join(cells)+" |")
    lines += ["", "## Thời gian", "", "| Cấu hình | Adapter wall tổng (s) | Trung bình/PDF (s) | Weighted/trang chọn (s) |", "|---|---:|---:|---:|"]
    lines.extend(f"| {r['model']} | {r['recognition_wall_seconds']:.3f} | {r['average_seconds_per_document']:.3f} | {r['weighted_seconds_per_selected_page']:.3f} |" for r in timing)
    lines += ["", "- Các call Tesseract trùng ảnh được cache theo pixels+config; timing này phản ánh memoized adapter, không phải đo chạy lại độc lập toàn bộ ảnh. Số cache hits được lưu riêng.",
        "- Không có timing-only pass. Đây không phải thời gian PDF full-pipeline; hai nhánh replay không có timing OCR mới để so tốc độ.","",
        "## Artifact và giới hạn", "",
        "Mỗi cohort có predictions.jsonl, metrics/field_errors/document_success/summary, trace theo document, physical-page mapping, fingerprints và checkpoint. `recognition_timing_per_document.csv` lưu thời gian từng PDF/config.",
        "Không có transcription GT cho dòng/từ nên không báo recognition CER/WER. Chọn183trang bằng metadata GT là giao thức đánh giá có oracle page selection, không phải đánh giá tự động chọn trang. Preserved GT/source hashes checked before completion."]
    (root/"REPORT.md").write_text("\n".join(lines)+"\n")
    dump(root/"manifest.json",dict(status="completed",mode=MODE,documents=100,selected_pages=183,crops=6619,
        full_psm_configurations=[6,7,13],post_correct=False,unselected_page_ocr_used=False,document_pass=passes))
    print(json.dumps(dict(passes=passes,timing=timing),ensure_ascii=False,indent=2),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("--stage",choices=("all","full","report"),default="all")
    args=parser.parse_args()
    root=args.root.resolve();root.mkdir(parents=True,exist_ok=True)
    if args.stage in ("all","full"):
        for name,saved in SAVED.items():
            run_cohort(root,name,None,saved=saved)
        config=read(ROOT/"conf/recognizers/pytesseract_vie.json")
        for psm in (6,7,13):
            run_cohort(root,f"pytesseract_psm{psm}",None,config={**config,"psm":psm})
    if args.stage in ("all","report"):
        report(root)


if __name__=="__main__":
    main()
