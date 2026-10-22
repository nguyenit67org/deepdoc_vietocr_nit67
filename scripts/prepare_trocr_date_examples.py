"""Export five fixed saved header-date examples, without OCR inference."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.analyze_trocr_saved_errors import read,write,render_case,EXPERIMENT,RUNS
from scripts.review_trocr_handwriting_subset import ANALYSIS,records_for_case


def main():
    import argparse
    import pandas as pd
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--printed",action="store_true",help="Additional printed-only candidate dates, requiring visual confirmation")
    args=parser.parse_args()
    output=ROOT/("ocr-collab/artifacts/trocr_documentDate_printed5_20261020" if args.printed else "ocr-collab/artifacts/trocr_documentDate_review5_20261020")
    output.mkdir(exist_ok=False)
    (output/"evidence").mkdir()
    parents=pd.read_csv(ANALYSIS/"parent_crop_diagnostics.csv",keep_default_na=False).to_dict("records")
    predictions={run:{r["document_id"]:r for r in map(json.loads,(EXPERIMENT/run/"candidate_predictions.jsonl").read_text().splitlines())} for run in RUNS}
    cases=[]
    selection=(("06+NQ-HĐND_2026-03-28",7),("117+2020+TT-BTC_2020-12-31",5),
        ("119+2020+TT-BTC_2020-12-31",4),("2399+QĐ-BTC_2017-11-21",4),("49+KH-UBND_2026-02-04",5)) if args.printed else (
        ("118+2020+TT-BTC_2020-12-31",4),("156+2020+NĐ-CP_2020-12-31",4),
        ("1321+QĐ-UBND_2025-05-12",6),("03+QĐLT-SGDHCM-SGDHN_2016-09-08",5),("1679+QĐ-TTg_2026-08-28",7))
    for document,index in selection:
        case=next(r for r in parents if (r["document_id"],r["page_index_0based"],r["crop_index"])==(document,0,index))
        case={**case,"case_id":f"{'printed_date' if args.printed else 'date'}_{len(cases):02d}","selection_stratum":"printed_documentDate_candidate" if args.printed else "documentDate_header_error",
            "saved_documentDate":{run:predictions[run][document]["prediction"]["documentDate"] for run in RUNS}}
        render_case(case,*records_for_case(case),output/"evidence"/(case["case_id"]+".png"))
        cases.append(case)
    write(output/"selected_cases.json",cases)
    print(output)


if __name__=="__main__":
    main()
