#!/usr/bin/env python3
"""Turn 2J composite catalog sheets into per-SKU web catalog records.

The source images are read-only working copies downloaded from Google Drive.
This script uses local OCR, creates a compact crop for every detected item number,
and writes assets/catalog-products.js for the static prototype.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/priority-source")
OUTPUT = Path(os.environ.get("CATALOG_ASSET_OUTPUT", ROOT / "assets" / "catalog"))
JS_OUTPUT = Path(os.environ.get("CATALOG_JS_OUTPUT", ROOT / "catalog-products.js"))

UNIT_MAP = {"PC": "unit", "PK": "pack", "DZ": "dozen", "DP": "displayPack"}


def run_ocr(path: Path, mode: str) -> str:
    proc = subprocess.run(
        ["tesseract", str(path), "stdout", "--psm", mode, "tsv"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return proc.stdout


def sheet_prefixes(name: str) -> tuple[str, ...]:
    upper = name.upper()
    match = re.search(r"AISLE\d+[- _]+(.+?)(?:\.[A-Z0-9]+)?$", upper)
    if not match:
        return ()
    prefixes = []
    for prefix in re.findall(r"(?:^|[ _-])([A-Z]{1,5})\d+", match.group(1)):
        if prefix not in prefixes:
            prefixes.append(prefix)
    if not prefixes:
        first = re.match(r"([A-Z]{1,5})", match.group(1))
        if first:
            prefixes.append(first.group(1))
    if "CA" in prefixes:
        for related in ("CB", "CS", "CAP"):
            if related not in prefixes:
                prefixes.append(related)
    return tuple(prefixes)


def normalize_code(value: str) -> str:
    value = value.upper().replace("—", "-").replace("_", "-")
    value = re.sub(r"[^A-Z0-9-]", "", value)
    return value.strip("-")


def valid_code(value: str, prefixes: tuple[str, ...]) -> bool:
    if len(value) > 18:
        return False
    for prefix in prefixes:
        suffix = value[len(prefix):] if value.startswith(prefix) else ""
        if prefix == "BNO" and re.fullmatch(r"(?:\d[A-Z0-9-]*|[A-Z]{2,7})", suffix):
            return True
        if prefix != "BNO" and re.fullmatch(r"\d[A-Z0-9-]*", suffix):
            return True
    return False


def extract_words(path: Path, prefixes: tuple[str, ...]) -> tuple[list[dict], list[dict]]:
    raw = run_ocr(path, "11")
    rows = list(csv.DictReader(io.StringIO(raw), delimiter="\t"))
    words = []
    for row in rows:
        text = (row.get("text") or "").strip()
        try:
            conf = float(row.get("conf", "-1"))
        except ValueError:
            conf = -1
        if not text or conf < 15:
            continue
        item = {
            "text": text,
            "left": int(row["left"]),
            "top": int(row["top"]),
            "width": int(row["width"]),
            "height": int(row["height"]),
            "line": (row["block_num"], row["par_num"], row["line_num"]),
        }
        words.append(item)

    candidates = []
    for word in words:
        code = normalize_code(word["text"])
        if valid_code(code, prefixes):
            candidates.append({**word, "code": code})

    # Some sheets live in one aisle group but use a different actual SKU prefix
    # (for example an MM sheet containing SB2604). Only use this broad fallback
    # when the expected-prefix pass found nothing.
    if not candidates:
        blocked = {"OZ", "PCS", "PC", "PK", "DZ", "CASE", "SIZE"}
        for word in words:
            code = normalize_code(word["text"])
            match = re.fullmatch(r"([A-Z]{1,4})(\d[A-Z0-9-]{2,})", code)
            if match and len(code) <= 18 and match.group(1) not in blocked:
                candidates.append({**word, "code": code})

    # OCR sometimes separates a prefix and number (for example "CB 24").
    for index, word in enumerate(words[:-1]):
        prefix = normalize_code(word["text"])
        nxt = words[index + 1]
        number = normalize_code(nxt["text"])
        gap = nxt["left"] - (word["left"] + word["width"])
        same_line = word["line"] == nxt["line"]
        if prefix in prefixes and re.fullmatch(r"\d[A-Z0-9-]*", number) and same_line and gap < 100:
            candidates.append({
                **word,
                "code": prefix + number,
                "width": nxt["left"] + nxt["width"] - word["left"],
                "height": max(word["height"], nxt["height"]),
            })

    # One location per visible item number; prefer the clearest/largest occurrence.
    best = {}
    for item in candidates:
        score = item["width"] * item["height"]
        if item["code"] not in best or score > best[item["code"]][0]:
            best[item["code"]] = (score, item)
    return words, [value[1] for value in best.values()]


def group_rows(items: list[dict], height: int) -> list[list[dict]]:
    rows: list[list[dict]] = []
    threshold = max(55, int(height * 0.025))
    for item in sorted(items, key=lambda x: x["top"] + x["height"] / 2):
        cy = item["top"] + item["height"] / 2
        placed = False
        for row in rows:
            row_y = sum(x["top"] + x["height"] / 2 for x in row) / len(row)
            if abs(cy - row_y) <= threshold:
                row.append(item)
                placed = True
                break
        if not placed:
            rows.append([item])
    for row in rows:
        row.sort(key=lambda x: x["left"] + x["width"] / 2)
    return rows


def crop_box(item: dict, rows: list[list[dict]], width: int, height: int) -> tuple[int, int, int, int]:
    if item.get("full"):
        return 0, 0, width, height
    row_index = next(i for i, row in enumerate(rows) if item in row)
    row = rows[row_index]
    col = row.index(item)
    centers = [x["left"] + x["width"] / 2 for x in row]
    left = 0 if col == 0 else int((centers[col - 1] + centers[col]) / 2)
    right = width if col == len(row) - 1 else int((centers[col] + centers[col + 1]) / 2)

    row_centers = [sum(x["top"] + x["height"] / 2 for x in r) / len(r) for r in rows]
    top = 0 if row_index == 0 else int((row_centers[row_index - 1] + row_centers[row_index]) / 2)
    bottom = height if row_index == len(rows) - 1 else int((row_centers[row_index] + row_centers[row_index + 1]) / 2)

    # Include a little neighboring context without crossing into another product.
    pad_x = min(24, left)
    pad_y = min(24, top)
    return max(0, left - pad_x), max(0, top - pad_y), min(width, right + 24), min(height, bottom + 24)


def price_and_unit(text: str) -> tuple[float | None, str]:
    clean = text.upper().replace("OZ", "OZ ")
    matches = re.findall(r"\$\s*(\d+(?:\.\d{1,2})?)\s*/\s*(PC|PK|DZ|DP)", clean)
    if not matches:
        matches = re.findall(r"\$\s*(\d+(?:\.\d{1,2})?).{0,5}\b(PC|PK|DZ|DP)\b", clean)
    if not matches:
        return None, "unit"
    amount, unit = matches[0]
    return float(amount), UNIT_MAP.get(unit, "unit")


def ocr_price(path: Path) -> tuple[float | None, str]:
    proc = subprocess.run(
        ["tesseract", str(path), "stdout", "--psm", "6"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return price_and_unit(proc.stdout)


def description_from_ocr(text: str, code: str) -> str:
    candidates = []
    for raw in text.splitlines():
        line = re.sub(re.escape(code), " ", raw, flags=re.I)
        line = re.sub(r"\$\s*\d+(?:\.\d{1,2})?\s*/?\s*(?:PC|PK|DZ|DP|BK|EA)?", " ", line, flags=re.I)
        line = re.sub(r"\b\d+\s*(?:PCS?|PC|PK|DZ|DP|BK|CASE|CT)\b", " ", line, flags=re.I)
        line = re.sub(r"[^A-Za-z0-9&+/'., -]", " ", line)
        line = re.sub(r"\s+", " ", line).strip(" -.,")
        if len(line) >= 4 and re.search(r"[A-Za-z]{3}", line) and not re.fullmatch(r"[A-Z0-9-]{3,18}", line):
            if line not in candidates:
                candidates.append(line)
    description = " · ".join(candidates[:3])
    if len(description) > 170:
        description = description[:167].rsplit(" ", 1)[0] + "…"
    return description or f"Catalog photo for item {code}."


def crop_text(words: list[dict], box: tuple[int, int, int, int]) -> str:
    left, top, right, bottom = box
    return " ".join(
        word["text"] for word in words
        if left <= word["left"] + word["width"] / 2 <= right
        and top <= word["top"] + word["height"] / 2 <= bottom
    )


def save_crop(image: Image.Image, box: tuple[int, int, int, int], destination: Path) -> None:
    crop = image.crop(box).convert("RGB")
    crop = ImageOps.contain(crop, (720, 720), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (720, 720), "white")
    canvas.paste(crop, ((720 - crop.width) // 2, (720 - crop.height) // 2))
    canvas.save(destination, "WEBP", quality=78, method=6)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for old_crop in OUTPUT.glob("*.webp"):
        old_crop.unlink()
    products = {}
    stats = Counter()
    sheets = sorted(path for path in SOURCE.iterdir() if path.is_file())
    for sheet_index, path in enumerate(sheets, 1):
        prefixes = sheet_prefixes(path.name)
        if not prefixes:
            continue
        words, items = extract_words(path, prefixes)
        page_prices = set(re.findall(r"\$\s*(\d+(?:\.\d{1,2})?)\s*/\s*(PC|PK|DZ|DP)", crop_text(words, (0, 0, 10**9, 10**9)).upper()))
        page_default = next(iter(page_prices)) if len(page_prices) == 1 else None
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            if not items:
                tail = re.sub(r"^.*?AISLE\d+[- _]+", "", path.name.upper())
                fallback = re.search(r"(?:^|[ _-])([A-Z]{1,5})(\d+)", tail)
                if fallback:
                    items = [{"code": fallback.group(1) + fallback.group(2), "left": image.width // 2, "top": image.height // 2, "width": 1, "height": 1, "full": True}]
            rows = group_rows(items, image.height)
            for item in items:
                code = item["code"]
                # Duplicate Drive sheets are common. Keep the first usable crop per SKU.
                if code in products:
                    stats["duplicates"] += 1
                    continue
                box = crop_box(item, rows, image.width, image.height)
                price, unit = price_and_unit(crop_text(words, box))
                category = next((prefix for prefix in ("BNO", "CAP", "MM", "CB", "CA", "CS") if code.startswith(prefix)), re.match(r"[A-Z]+", code).group(0))
                filename = re.sub(r"[^a-z0-9-]", "-", code.lower()) + ".webp"
                save_crop(image, box, OUTPUT / filename)
                ocr_result = subprocess.run(
                    ["tesseract", str(OUTPUT / filename), "stdout", "--psm", "6"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).stdout
                if price is None:
                    price, unit = price_and_unit(ocr_result)
                if price is None and page_default:
                    price, raw_unit = page_default
                    price, unit = float(price), UNIT_MAP.get(raw_unit, "unit")
                products[code] = {
                    "id": f"drive-{code.lower()}",
                    "driveCatalog": True,
                    "sourceCode": code,
                    "sourceSheet": re.sub(r"^\d+_", "", path.name),
                    "description": description_from_ocr(ocr_result, code),
                    "descriptionKo": description_from_ocr(ocr_result, code),
                    "name": code,
                    "nameKo": code,
                    "category": category,
                    "price": price if price is not None else 0,
                    "pricePending": price is None,
                    "unitLabel": unit,
                    "stock": None,
                    "image": f"assets/catalog/{filename}",
                    "color": "#e8e2d9",
                    "tags": [code, category, "Drive catalog"],
                    "tagsKo": [code, category, "Drive 카탈로그"],
                }
                stats[category] += 1
        print(f"[{sheet_index:02d}/{len(sheets)}] {path.name}: {len(items)} item code(s)", flush=True)

    ordered = [products[key] for key in sorted(products, key=lambda x: (re.match(r"[A-Z]+", x).group(0), x))]
    payload = "// Generated from the connected 2J Group Drive catalog.\nconst DRIVE_PRODUCTS = " + json.dumps(ordered, ensure_ascii=False, indent=2) + ";\n"
    JS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    JS_OUTPUT.write_text(payload, encoding="utf-8")
    print(json.dumps({"products": len(ordered), "categories": dict(stats)}, indent=2))


if __name__ == "__main__":
    main()
