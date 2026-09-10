import os
import re
import sys
import json
import time
import httpx
import requests
from dotenv import dotenv_values
from bs4 import BeautifulSoup
import pypdf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, 'data', 'demo', 'raw')
ENV_FILE = os.path.join(BASE_DIR, '.env.local')

os.makedirs(RAW_DIR, exist_ok=True)

# Load Viettel AI OCR API key securely without printing or logging it
env_vars = dotenv_values(ENV_FILE)
OCR_KEY = env_vars.get('VAI_OCR_API_KEY')
if not OCR_KEY:
    print("ERROR: VAI_OCR_API_KEY not found in .env.local", file=sys.stderr)
    sys.exit(1)

OCR_URL = 'https://ipa.viettelai.vn/uat/gateway/api/v1/services/ocr/vbhc'
OCR_HEADERS = {
    'Authorization': f'Bearer {OCR_KEY}',
    'User-Agent': 'curl/7.81.0'
}

TOTAL_TARGET = 40

def sanitize_filename(name):
    clean = re.sub(r'[^\w\-\.]', '_', name)
    clean = re.sub(r'_+', '_', clean).strip('_')
    return clean

def detect_document_format(pdf_path):
    try:
        reader = pypdf.PdfReader(pdf_path)
        total_text_len = 0
        for page in reader.pages:
            t = page.extract_text() or ''
            total_text_len += len(t.strip())
        if total_text_len > 100:
            return "pdf_in"
        else:
            return "scan"
    except Exception:
        return "scan"

def get_smart_slice(pdf_path, max_pages=3):
    try:
        reader = pypdf.PdfReader(pdf_path)
        total_pages = len(reader.pages)
        if total_pages <= max_pages:
            return pdf_path
        
        writer = pypdf.PdfWriter()
        writer.add_page(reader.pages[0])
        if total_pages > 1:
            writer.add_page(reader.pages[1])
        
        sig_page_idx = None
        for idx in range(2, min(total_pages, 80)):
            text = (reader.pages[idx].extract_text() or '').lower()
            if any(w in text for w in ['kt. bộ trưởng', 'kt. thủ tướng', 'thứ trưởng', 'chủ tịch', 'tổng giám đốc', 'bộ trưởng', 'thủ tướng chính phủ', 'tm. chính phủ']) and any(w in text for w in ['nơi nhận', 'k/t', 'kt.']):
                sig_page_idx = idx
                break
        
        if sig_page_idx:
            writer.add_page(reader.pages[sig_page_idx])
        elif total_pages > 2:
            writer.add_page(reader.pages[2])
            
        out_slice = f"/tmp/smart_{os.path.basename(pdf_path)}"
        with open(out_slice, 'wb') as f:
            writer.write(f)
        return out_slice
    except Exception:
        return pdf_path

def call_ocr_api(pdf_path):
    upload_path = get_smart_slice(pdf_path)
    for attempt in range(3):
        try:
            with open(upload_path, 'rb') as f:
                files = {'file': (os.path.basename(pdf_path), f, 'application/pdf')}
                res = requests.post(OCR_URL, headers=OCR_HEADERS, files=files, timeout=90)
            if res.status_code == 200:
                return res.json()
            else:
                print(f"OCR API HTTP {res.status_code} for {os.path.basename(pdf_path)} (attempt {attempt+1})", flush=True)
                time.sleep(2)
        except Exception as e:
            print(f"Error calling OCR API for {os.path.basename(pdf_path)}: {e} (attempt {attempt+1})", flush=True)
            time.sleep(2)
    return None

def build_label_json(ocr_result, metadata_info, pdf_path):
    info_item = {
        "type": {"value": "", "type": "string"},
        "title": {"value": "", "type": "string"},
        "code": {"value": "", "type": "string"},
        "documentDate": {"value": "", "type": "string"},
        "officeSender": {"value": "", "type": "string"},
        "recipients": {"value": "", "type": "string"},
        "signer_title": {"value": "", "type": "string"},
        "signer": {"value": "", "type": "string"},
        "province": {"value": "", "type": "string"},
        "receiverDate": {"value": "", "type": "string"},
        "priority_level": {"value": "0_BÌNH THƯỜNG", "type": "string"},
        "security_level": {"value": "0_BÌNH THƯỜNG", "type": "string"}
    }

    has_hw = False
    if ocr_result and 'information' in ocr_result and len(ocr_result['information']) > 0:
        api_info = ocr_result['information'][0]
        for k in info_item.keys():
            if k in api_info and isinstance(api_info[k], dict):
                val = api_info[k].get('value')
                info_item[k]["value"] = val if val is not None else ""
        
        if info_item["signer"]["value"] or info_item["signer_title"]["value"]:
            has_hw = True

    # Fallback/infer from metadata if fields are empty
    if not info_item["title"]["value"] and metadata_info.get("title"):
        info_item["title"]["value"] = metadata_info["title"]
    if not info_item["code"]["value"] and metadata_info.get("code"):
        info_item["code"]["value"] = metadata_info["code"]
    if not info_item["officeSender"]["value"] and metadata_info.get("officeSender"):
        info_item["officeSender"]["value"] = metadata_info["officeSender"]
    if not info_item["type"]["value"] and metadata_info.get("type"):
        info_item["type"]["value"] = metadata_info["type"]
    if not info_item["documentDate"]["value"] and metadata_info.get("date"):
        info_item["documentDate"]["value"] = metadata_info["date"]

    doc_format = detect_document_format(pdf_path)

    label_data = {
        "information": [info_item],
        "metadata": {
            "document_format": {
                "value": doc_format,
                "type": "string"
            },
            "has_handwriting": {
                "value": has_hw,
                "type": "boolean"
            },
            "field": {
                "value": "Chứng khoán",
                "type": "string"
            },
            "source_name": {
                "value": metadata_info.get("source_name", ""),
                "type": "string"
            },
            "source_url_detail": {
                "value": metadata_info.get("source_url_detail", ""),
                "type": "string"
            },
            "source_url_pdf": {
                "value": metadata_info.get("source_url_pdf", ""),
                "type": "string"
            }
        }
    }
    return label_data

def crawl_hnx(client, collected):
    print("=== BẮT ĐẦU THU THẬP TỪ TRANG 1 (HNX) - KHÔNG LỌC THỜI GIAN ===", flush=True)
    headers = {
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'
    }
    
    exclude_keywords = [
        'báo cáo tài chính', 'bctc', 'báo cáo thường niên', 'báo cáo quản trị',
        'bcqt', 'bản cáo bạch', 'prospectus', 'báo cáo tình hình'
    ]

    page = 1
    while len(collected) < TOTAL_TARGET:
        data = {
            'pNumPage': page,
            'pTieuDeTin': '',
            'pFromDate': '',
            'pToDate': '',
            'pOrderBy': '',
            'pNumRecord': 100
        }
        try:
            r = client.post('https://portal.hnx.vn/ModuleArticles/ArticlesCPEtfs/NextPageTinTCPHChuaGD_NY', data=data, headers=headers)
        except Exception as e:
            print(f"Error fetching HNX page {page}: {e}", flush=True)
            break
            
        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.find_all('tr')
        if not rows:
            break

        new_on_page = 0
        for row in rows:
            title = ""
            art_id = None
            date_str = ""
            tds = row.find_all('td')
            if len(tds) >= 2:
                date_str = tds[1].text.strip().split()[0]  # e.g. 25/01/2022

            for a in row.find_all('a'):
                oc = a.get('onclick', '')
                if 'funcViewDetailArticlesByID' in oc:
                    title = a.text.strip()
                elif 'funcShowFileAttach' in oc:
                    m = re.search(r'funcShowFileAttach\((\d+)', oc)
                    if m:
                        art_id = m.group(1)
            
            if not art_id or not title:
                continue

            t_lower = title.lower()
            if any(ek in t_lower for ek in exclude_keywords):
                print(f"[HNX] Loại bỏ (Báo cáo/Tài chính): {title}", flush=True)
                continue

            try:
                r_attach = client.post('https://portal.hnx.vn/ModuleArticles/ArticlesCPEtfs/ArticlesFileAttach', data={'pArticlesID': art_id}, headers=headers)
                attach_soup = BeautifulSoup(r_attach.text, 'html.parser')
                pdf_links = [a.get('href') for a in attach_soup.find_all('a') if a.get('href') and a.get('href').lower().endswith('.pdf')]
            except Exception as e:
                print(f"[HNX] Lỗi lấy attachment id {art_id}: {e}", flush=True)
                continue

            for pdf_url in pdf_links:
                if len(collected) >= TOTAL_TARGET:
                    break

                doc_type = "Văn bản hành chính"
                for candidate in ["Nghị quyết", "Quyết định", "Thông báo", "Biên bản", "Công văn", "Giấy mời", "Giấy ủy quyền", "Hợp đồng"]:
                    if candidate.lower() in t_lower:
                        doc_type = candidate
                        break

                orig_name = os.path.basename(pdf_url)
                clean_name = sanitize_filename(orig_name)
                if not clean_name.lower().endswith('.pdf'):
                    clean_name += '.pdf'

                save_path = os.path.join(RAW_DIR, clean_name)
                
                # Check if already downloaded
                if not os.path.exists(save_path) or os.path.getsize(save_path) < 100:
                    print(f"[HNX] Tải PDF ({art_id}): {clean_name}", flush=True)
                    try:
                        res_pdf = client.get(pdf_url, headers={'User-Agent': 'Mozilla/5.0'})
                        if res_pdf.status_code == 200 and len(res_pdf.content) > 500:
                            with open(save_path, 'wb') as f:
                                f.write(res_pdf.content)
                        else:
                            print(f"[HNX] Tải không thành công: {pdf_url}", flush=True)
                            continue
                    except Exception as e:
                        print(f"[HNX] Lỗi tải PDF {pdf_url}: {e}", flush=True)
                        continue
                else:
                    print(f"[HNX] File đã tồn tại sẵn: {clean_name}", flush=True)

                meta = {
                    "title": title,
                    "type": doc_type,
                    "code": "",
                    "officeSender": "",
                    "date": date_str,
                    "source_name": "Sở Giao dịch Chứng khoán Hà Nội (HNX)",
                    "source_url_detail": "https://portal.hnx.vn/thong-tin-cong-bo-ny-tcphchuagd.html",
                    "source_url_pdf": pdf_url
                }
                collected.append((save_path, meta))
                new_on_page += 1
                print(f"-> Thu thập thành công [{len(collected)}/{TOTAL_TARGET}]: {clean_name}", flush=True)

        if new_on_page == 0:
            break
        page += 1

    print(f"=== KẾT THÚC HNX: Đã thu thập {len(collected)} file hợp lệ ===\n", flush=True)

def crawl_hsx(client, collected):
    needed = TOTAL_TARGET - len(collected)
    print(f"=== BẮT ĐẦU THU THẬP TỪ TRANG 2 (HSX) - CẦN THÊM {needed} FILE ===", flush=True)
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)',
        'Referer': 'https://www.hsx.vn/'
    }
    
    exclude_keywords = [
        'báo cáo tài chính', 'bctc', 'báo cáo thường niên', 'báo cáo quản trị',
        'bcqt', 'bản cáo bạch', 'prospectus', 'tài liệu hướng dẫn', 'training', 'câu hỏi'
    ]

    # First attempt: 2000-01-01 to 2017-12-31, then subsequent years if needed
    date_ranges = [
        ('2000-01-01', '2017-12-31'),
        ('2018-01-01', '2020-12-31'),
        ('2021-01-01', '2026-12-31')
    ]

    for start_d, end_d in date_ranges:
        if len(collected) >= TOTAL_TARGET:
            break

        print(f"[HSX] Quét khoảng thời gian: {start_d} đến {end_d}", flush=True)
        params = {
            'pageIndex': 1,
            'pageSize': 100,
            'aliasCate': 'van-ban-phap-quy',
            'startDate': start_d,
            'endDate': end_d
        }
        try:
            r = client.get('https://api.hsx.vn/n/api/v1/1/news/cate', params=params, headers=headers)
            items = r.json().get('data', {}).get('list', [])
        except Exception as e:
            print(f"[HSX] Lỗi truy vấn API {start_d} - {end_d}: {e}", flush=True)
            continue

        for item in items:
            if len(collected) >= TOTAL_TARGET:
                break
            
            title = item.get('title', '').strip()
            code = item.get('code', '').strip()
            item_id = item.get('id')
            if code == '0':
                code = ""
            
            t_lower = title.lower()
            if any(ek in t_lower for ek in exclude_keywords):
                print(f"[HSX] Loại bỏ tài liệu: {title}", flush=True)
                continue
            
            try:
                r_media = client.get(f'https://api.hsx.vn/m/api/v1/1/mediafiles/9/{item_id}', headers=headers)
                media_list = r_media.json().get('data', {}).get('list', [])
            except Exception as e:
                print(f"[HSX] Lỗi lấy file media cho doc {item_id}: {e}", flush=True)
                continue

            pdf_files = [m for m in media_list if m.get('filePath', '').lower().endswith('.pdf')]
            for mf in pdf_files:
                if len(collected) >= TOTAL_TARGET:
                    break
                
                raw_path = mf.get('filePath', '')
                download_url = raw_path.replace('~', 'https://staticfile.hsx.vn')
                file_name = mf.get('fileName') or os.path.basename(raw_path)
                
                # Check for excluded file names (like slides/training)
                if any(ek in file_name.lower() for ek in ['training', 'cau hoi', 'thư ngỏ', 'thu ngo']):
                    continue

                clean_name = sanitize_filename(file_name)
                if not clean_name.lower().endswith('.pdf'):
                    clean_name += '.pdf'
                
                # Prefix with item_id if duplicate name
                save_path = os.path.join(RAW_DIR, clean_name)
                if any(p == save_path for p, _ in collected):
                    clean_name = f"{item_id}_{clean_name}"
                    save_path = os.path.join(RAW_DIR, clean_name)

                if not os.path.exists(save_path) or os.path.getsize(save_path) < 100:
                    print(f"[HSX] Tải PDF ({item_id}): {clean_name}", flush=True)
                    try:
                        res_pdf = client.get(download_url, headers={'User-Agent': 'Mozilla/5.0'})
                        if res_pdf.status_code == 200 and len(res_pdf.content) > 500:
                            with open(save_path, 'wb') as f:
                                f.write(res_pdf.content)
                        else:
                            print(f"[HSX] Tải không thành công: {download_url}", flush=True)
                            continue
                    except Exception as e:
                        print(f"[HSX] Lỗi tải {download_url}: {e}", flush=True)
                        continue
                else:
                    print(f"[HSX] File đã tồn tại sẵn: {clean_name}", flush=True)

                doc_type = "Văn bản pháp quy"
                for candidate in ["Thông báo", "Quyết định", "Nghị quyết", "Thông tư", "Nghị định", "Quy chế", "Quy định", "Hướng dẫn", "Chỉ thị", "Luật"]:
                    if candidate.lower() in t_lower:
                        doc_type = candidate
                        break

                meta = {
                    "title": title,
                    "type": doc_type,
                    "code": code,
                    "officeSender": "",
                    "date": "",
                    "source_name": "Sở Giao dịch Chứng khoán TP.HCM (HSX)",
                    "source_url_detail": f"https://www.hsx.vn/vi/van-ban-phap-quy/detail/{item_id}",
                    "source_url_pdf": download_url
                }
                collected.append((save_path, meta))
                print(f"-> Thu thập thành công [{len(collected)}/{TOTAL_TARGET}]: {clean_name}", flush=True)

    print(f"=== KẾT THÚC HSX: Tổng cộng đã thu thập {len(collected)} file ===\n", flush=True)

def main():
    collected = []
    client = httpx.Client(verify=False, follow_redirects=True, timeout=30)
    
    crawl_hnx(client, collected)
    
    if len(collected) < TOTAL_TARGET:
        crawl_hsx(client, collected)
        
    print(f"\n=======================================================", flush=True)
    print(f"ĐÃ THU THẬP ĐỦ {len(collected)} FILE PDF RAW.", flush=True)
    print(f"BẮT ĐẦU GỌI VIETTEL AI OCR API & TẠO FILE NHÃN JSON...", flush=True)
    print(f"=======================================================\n", flush=True)
    
    success_count = 0
    for idx, (pdf_path, meta) in enumerate(collected, 1):
        filename = os.path.basename(pdf_path)
        base_name, _ = os.path.splitext(filename)
        json_path = os.path.join(RAW_DIR, f"{base_name}.json")

        if os.path.exists(json_path) and os.path.getsize(json_path) > 100:
            print(f"[{idx}/{len(collected)}] Nhãn đã tồn tại: {base_name}.json -> Bỏ qua OCR", flush=True)
            success_count += 1
            continue

        print(f"[{idx}/{len(collected)}] Đang gọi OCR Viettel AI cho: {filename}...", flush=True)
        ocr_result = call_ocr_api(pdf_path)
        label_data = build_label_json(ocr_result, meta, pdf_path)
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(label_data, f, ensure_ascii=False, indent=4)
        
        print(f"  -> Lưu nhãn thành công: {base_name}.json", flush=True)
        success_count += 1
        time.sleep(1)

    print(f"\n=======================================================", flush=True)
    print(f"HOÀN THÀNH TOÀN BỘ! Đã xử lý {success_count}/{len(collected)} file PDF + JSON trong {RAW_DIR}", flush=True)
    print(f"=======================================================\n", flush=True)

if __name__ == '__main__':
    main()
