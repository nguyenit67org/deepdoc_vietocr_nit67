"""Conservative layout-guided wrapper around remove_red.py V5 color logic.

No PDF rewriting, model loading, extraction or ground-truth lookup. Masks
are applied AFTER all V5 writes, including dark-stroke recovery.
"""
import time
import unicodedata
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image


def analyse(img):
    blue, green, red = img.astype(np.int16).transpose(2, 0, 1)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    rg, rb = red - green, red - blue
    black = (np.abs(rg) < 25) & (np.abs(rb) < 25) & (gray < 130)
    near = cv2.dilate(black.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    overlap = (red < 115) & (np.minimum(green, blue) < 75) & (gray < 90)
    protected = ((blue > red) & (blue > green)) | black | (near & (gray < 160) & ((rg < 35) | overlap))
    hue = (hsv[..., 0] <= 15) | (hsv[..., 0] >= 145)
    sat = hsv[..., 1]
    red_mask = ((hue & (sat >= 25) & (rg >= 18) & (rb >= 12) & (red > 80))
                | ((lab[..., 1] >= 134) & (rg >= 15) & (red > 80))
                | (hue & (sat >= 15) & (rg >= 10) & (red > 120)))
    removal = cv2.dilate((red_mask & ~protected).astype(np.uint8),
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))) > 0
    return SimpleNamespace(red=red, rg=rg, rb=rb, gray=gray, black=black,
                           removal=removal & ~protected,
                           isolated=overlap & (rg > 15) & (rb > 12) & ~near,
                           stroke=protected & (rg > 15) & (rb > 12) & (gray < 110))


def find_red_regions(img):
    blue, green, red = img.astype(np.int16).transpose(2, 0, 1)
    strong = (red - green > 50) & (red - blue > 50) & (red > 100)
    grouped = cv2.dilate(strong.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)))
    _, _, stats, _ = cv2.connectedComponentsWithStats(grouped, connectivity=8)
    regions = []
    for x, y, w, h, _ in stats[1:]:
        area = int(w * h)
        count = int(strong[y:y+h, x:x+w].sum())
        if area >= max(2500, round(img.shape[0] * img.shape[1] * 0.002)) and count >= 400:
            regions.append((int(x), int(y), int(w), int(h), count / area))
    regions.sort(key=lambda r: r[2] * r[3], reverse=True)
    kept = []
    for r in regions:
        x, y, w, h, _ = r
        if not any(x >= ax and y >= ay and x+w <= ax+aw and y+h <= ay+ah for ax, ay, aw, ah, _ in kept):
            kept.append(r)
    return kept


def remove_red_from_bgr(img, *, dense_threshold=0.18, dark_red_max=145, min_black_neighbors=8):
    """V5 color operations on opaque rendered BGR pages (alpha is absent)."""
    if img.dtype != np.uint8 or img.ndim != 3 or img.shape[2] != 3:
        raise ValueError("Expected BGR uint8 image")
    if not 0 <= dense_threshold <= 1 or not 1 <= dark_red_max <= 255 or not 0 <= min_black_neighbors <= 361:
        raise ValueError("Invalid red-removal recovery thresholds")
    a = analyse(img)
    result = img.copy()
    result[a.removal] = 255
    if a.isolated.any():
        pixels = img.reshape(-1, 3).astype(np.uint32)
        packed = (pixels[:, 0] << 16) | (pixels[:, 1] << 8) | pixels[:, 2]
        colors, counts = np.unique(packed, return_counts=True)
        color = int(colors[counts.argmax()])
        result[a.isolated] = [(color >> 16) & 255, (color >> 8) & 255, color & 255]
    result[a.stroke] = a.gray[a.stroke, None]
    height, width = img.shape[:2]
    boxes = []
    for x, y, w, h, density in find_red_regions(img):
        if density >= dense_threshold:
            margin = max(10, round(0.25 * max(w, h)))
            boxes.append((max(0, y-margin), min(height, y+h+margin), max(0, x-margin), min(width, x+w+margin)))
    if boxes and a.black.any():
        top = max(0, min(b[0] for b in boxes)-9)
        bottom = min(height, max(b[1] for b in boxes)+9)
        left = max(0, min(b[2] for b in boxes)-9)
        right = min(width, max(b[3] for b in boxes)+9)
        sl = np.s_[top:bottom, left:right]
        count = cv2.boxFilter(a.black[sl].astype(np.uint8), cv2.CV_32S, (19, 19), normalize=False)
        targets = np.zeros(count.shape, bool)
        for y0, y1, x0, x1 in boxes:
            targets[y0-top:y1-top, x0-left:x1-left] = True
        candidate = targets & (a.rg[sl] > 15) & (a.rb[sl] > 12) & (a.red[sl] > 45) & (a.red[sl] < dark_red_max) & (count >= min_black_neighbors)
        recovered = np.minimum(np.rint(a.red[sl] * 0.55), 100).astype(np.uint8)
        result[sl][candidate] = recovered[candidate, None]
    return result


def masked_output(original, candidate, keep_mask, cleanup_mask):
    result = original.copy()
    allowed = cleanup_mask & ~keep_mask
    result[allowed] = candidate[allowed]
    return result


def _fold(text):
    return " ".join("".join(c for c in unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
                            if not unicodedata.combining(c)).split())


def process_red_pages(images, layouts, ocr, cfg):
    """Probe only merged red ROIs. Unknown regions fail closed.

    V1 allows cleanup only for compact seal detections containing an
    organization anchor, with no urgency/role/person-like line. Absence of
    recognized text never authorizes cleanup. This is a heuristic, not a
    guarantee of stamp semantics; keep disabled pending A/B validation.
    """
    from .ocr_page import prepare_ocr_page, finish_ocr_page

    if len(images) != len(layouts):
        raise ValueError("Images and layouts must have equal lengths")
    if cfg.remove_red_max_regions < 0 or not 0 <= cfg.remove_red_max_area_ratio <= 1 or cfg.remove_red_padding < 0:
        raise ValueError("Invalid red-removal probe limits")
    states, jobs, crops = [], [], []
    for image, blocks in zip(images, layouts):
        t0 = time.perf_counter()
        bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        b, g, r = bgr.astype(np.int16).transpose(2, 0, 1)
        # Broad cheap gate includes faint/small red text, unlike recovery's strong-red regions.
        red = (r-g >= 10) & (r-b >= 5) & (r > 80)
        keep = np.zeros(red.shape, bool)
        cleanup = np.zeros(red.shape, bool)
        regions = []
        if red.any():
            grouped = cv2.dilate(red.astype(np.uint8), np.ones((9, 9), np.uint8))
            for block in blocks:
                x0, y0, x1, y1 = _clip(block["bbox"], red.shape, 0)
                if x1 > x0 and y1 > y0 and red[y0:y1, x0:x1].any() and (x1-x0)*(y1-y0) <= red.size * cfg.remove_red_max_area_ratio:
                    grouped[y0:y1, x0:x1] = 1
            _, _, stats, _ = cv2.connectedComponentsWithStats(grouped, connectivity=8)
            for x, y, w, h, _ in stats[1:]:
                regions.append(_clip((x, y, x+w, y+h), red.shape, cfg.remove_red_padding))
        state = dict(original=bgr, keep=keep, cleanup=cleanup, regions=[], started=t0,
                     red_pixels=int(red.sum()), probe_crops=0)
        states.append(state)
        budget = 0
        for box in sorted(regions, key=lambda q: (q[1], q[0])):
            x0, y0, x1, y1 = box
            area = (x1-x0)*(y1-y0)
            record = {"bbox": list(box), "reason": "probe_limit", "lines": []}
            state["regions"].append(record)
            keep[y0:y1, x0:x1] = True
            if len([j for j in jobs if j[0] == len(states)-1]) >= cfg.remove_red_max_regions or budget+area > red.size*cfg.remove_red_max_area_ratio:
                continue
            budget += area
            roi = image.crop(box)
            prep, chunk = prepare_ocr_page(roi, ocr)
            roi.close()
            jobs.append((len(states)-1, box, record, prep, len(crops), len(chunk)))
            crops.extend(chunk)
            state["probe_crops"] += len(chunk)
    results, _ = ocr.text_recognizer[0](crops) if crops else ([], 0.0)
    if len(results) != len(crops):
        raise RuntimeError("Red probe recognition count mismatch")
    for pn, box, record, prep, start, count in jobs:
        lines = finish_ocr_page(prep, results[start:start+count], ocr)
        record["lines"] = [{**line,
                            "bbox": [line["bbox"][0]+box[0], line["bbox"][1]+box[1], line["bbox"][2]+box[0], line["bbox"][3]+box[1]],
                            "quad": [[x+box[0], y+box[1]] for x, y in line["quad"]]} for line in lines]
        texts = [line["text"] for line in lines]
        folded = _fold(" ".join(texts))
        critical = any(token in folded for token in ("hoa toc", "khan", "mat", "chu tich", "giam doc", "truong", "tm.", "kt.", "tl.", "tuq."))
        org_tokens = ("uy ban", "cong ty", "bo ", "so ", "cong an")
        person = any(2 <= len(t.split()) <= 6
                     and all(w.isalpha() and (w.istitle() or w.isupper()) for w in t.split())
                     and not any(token in _fold(t) for token in org_tokens) for t in texts)
        seal = any(block["type"].lower() == "seal" and _contained(block["bbox"], box) for block in layouts[pn])
        organization = any(token in folded for token in org_tokens)
        removable = bool(lines) and seal and organization and not critical and not person and 0.65 <= (box[2]-box[0])/max(1, box[3]-box[1]) <= 1.5
        record["reason"] = "organization_seal_candidate" if removable else "protected_or_uncertain"
        if removable:
            x0, y0, x1, y1 = box
            states[pn]["keep"][y0:y1, x0:x1] = False
            states[pn]["cleanup"][y0:y1, x0:x1] = True
            # Keep every non-organization OCR line, including black body text
            # crossing the seal. Organization lines are only a seal heuristic.
            for line in record["lines"]:
                if not any(token in _fold(line["text"]) for token in org_tokens):
                    lx0, ly0, lx1, ly1 = _clip(line["bbox"], states[pn]["keep"].shape, cfg.remove_red_padding)
                    states[pn]["keep"][ly0:ly1, lx0:lx1] = True
    outputs, reports, masks = [], [], []
    for image, state in zip(images, states):
        # Rejected/unprobed regions win even where padded ROIs overlap.
        for region in state["regions"]:
            if region["reason"] != "organization_seal_candidate":
                x0, y0, x1, y1 = region["bbox"]
                state["keep"][y0:y1, x0:x1] = True
        original = state["original"]
        if state["cleanup"].any():
            candidate = remove_red_from_bgr(original, dense_threshold=cfg.remove_red_dense_threshold,
                                            dark_red_max=cfg.remove_red_dark_red_max,
                                            min_black_neighbors=cfg.remove_red_min_black_neighbors)
            result = masked_output(original, candidate, state["keep"], state["cleanup"])
        else:
            result = original
        changed = int(np.any(result != original, axis=2).sum())
        outputs.append(Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB)) if changed else image)
        reports.append({"changed_pixels": changed, "red_pixels": state["red_pixels"],
                        "probe_crops": state["probe_crops"], "regions": state["regions"],
                        "seconds": time.perf_counter()-state["started"],
                        "timing_scope": "page_scan_to_output_wall_span_including_shared_batch"})
        masks.append((state["keep"], state["cleanup"]))
    return outputs, reports, masks


def _clip(box, shape, padding):
    h, w = shape
    return (max(0, min(w, int(box[0])-padding)), max(0, min(h, int(box[1])-padding)),
            max(0, min(w, int(np.ceil(box[2]))+padding)), max(0, min(h, int(np.ceil(box[3]))+padding)))


def _contained(inner, outer):
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]
