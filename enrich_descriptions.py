#!/usr/bin/env python3
"""Add concise, photo-grounded OCR descriptions to generated catalog data."""

from __future__ import annotations

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog-products.js"


def load_catalog() -> list[dict]:
    source = CATALOG.read_text(encoding="utf-8")
    payload = re.sub(r"^.*?const DRIVE_PRODUCTS\s*=\s*", "", source, count=1, flags=re.S)
    payload = re.sub(r";\s*$", "", payload)
    return json.loads(payload)


def clean_line(line: str, code: str) -> str:
    line = line.replace("|", " ").replace("_", " ")
    line = re.sub(re.escape(code), " ", line, flags=re.I)
    line = re.sub(r"\$\s*\d+(?:\.\d{1,2})?\s*/?\s*(?:PC|PK|DZ|DP|BK|EA)?", " ", line, flags=re.I)
    line = re.sub(r"\b\d+\s*(?:PCS?|PC|PK|DZ|DP|BK|CASE|CT)\b", " ", line, flags=re.I)
    line = re.sub(r"[^A-Za-z0-9&+/'., -]", " ", line)
    return re.sub(r"\s+", " ", line).strip(" -.,")


def description_from_text(text: str, product: dict) -> str:
    code = product["sourceCode"]
    rejected = {"assort", "assorted", "black", "white", "red", "blue", "pink", "green", "gold", "silver"}
    candidates = []
    for raw in text.splitlines():
        line = clean_line(raw, code)
        lower = line.lower()
        if len(line) < 4 or lower in rejected or not re.search(r"[A-Za-z]{3}", line):
            continue
        if re.fullmatch(r"[A-Z0-9-]{3,18}", line):
            continue
        if line not in candidates:
            candidates.append(line)

    # Prefer product-name-like lines and keep the result compact enough for cards.
    description = " · ".join(candidates[:3])
    if len(description) > 170:
        description = description[:167].rsplit(" ", 1)[0] + "…"
    return description or f"Catalog photo for item {code}."


def enrich(product: dict) -> tuple[str, str]:
    image = ROOT / product.get("image", "")
    if not image.is_file():
        return product["id"], f"Catalog photo for item {product['sourceCode']}."
    result = subprocess.run(
        ["tesseract", str(image), "stdout", "--psm", "6"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return product["id"], description_from_text(result.stdout, product)


def main() -> None:
    products = load_catalog()
    descriptions = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(enrich, product): product for product in products}
        for index, future in enumerate(as_completed(futures), 1):
            product_id, description = future.result()
            descriptions[product_id] = description
            if index % 250 == 0 or index == len(products):
                print(f"Descriptions {index}/{len(products)}", flush=True)

    for product in products:
        product["description"] = descriptions[product["id"]]
        product["descriptionKo"] = product["description"]

    output = "// Generated from the connected 2J Group Drive catalog.\nconst DRIVE_PRODUCTS = "
    output += json.dumps(products, ensure_ascii=False, indent=2) + ";\n"
    CATALOG.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
