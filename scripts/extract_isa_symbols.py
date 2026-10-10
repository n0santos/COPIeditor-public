"""
Extract P&ID symbols from ISA 5.1-2022 PDF.

For each symbol table, renders each page and crops the Symbol column
from every data row, saving individual PNGs to data/raw/isa5_1/symbols/.

Output structure:
  data/raw/isa5_1/symbols/
    5_1_1/   — Instrumentation device and function symbols
    5_4_1/   — Final control element symbols (valves)
    5_4_2/   — Actuator symbols
    5_4_3/   — Self-actuated final control elements
    5_4_4/   — Control valve failure positions
    5_2_3/   — Measurement primary elements
    5_2_4/   — Secondary instruments
    5_2_5/   — Auxiliary devices
    5_3_1/   — Line symbols: instrument-process connections
    5_3_2/   — Line symbols: instrument-instrument connections
    5_5/     — Functional diagramming
    index.json  — {filename: description} lookup for all symbols

Usage:
    python -m scripts.extract_isa_symbols
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("extract_isa_symbols")

PDF_PATH    = DATA_DIR / "isa5_1" / "ISA-5.1-2022.pdf"
SYMBOL_DIR  = DATA_DIR / "isa5_1" / "symbols"
RESOLUTION  = 150   # DPI for page rendering
SCALE       = RESOLUTION / 72.0

# Tables to extract: {table_id: [(page_idx_0based, col_header_hint)]}
# col_header_hint is a substring of the symbol column header text, used to
# detect which column contains the symbol.
TARGET_TABLES = {
    "5_1_1": list(range(33, 35)),   # p34-35
    "5_1_2": [34],                  # p35
    "5_2_1": [35],                  # p36
    "5_2_3": list(range(37, 42)),   # p38-42
    "5_2_4": [40, 41],              # p41-42
    "5_2_5": [41],                  # p42
    "5_3_1": [42],                  # p43
    "5_3_2": list(range(43, 45)),   # p44-45
    "5_4_1": list(range(45, 47)),   # p46-47  ← valves
    "5_4_2": list(range(47, 49)),   # p48-49  ← actuators
    "5_4_3": list(range(49, 52)),   # p50-52  ← self-actuated
    "5_4_4": [52],                  # p53
    "5_5":   [53],                  # p54
}

# Symbol column detection: typically column index 1 in "No | Symbol | Desc"
# but some tables have different layouts.
SYMBOL_COL_HINTS = ["Symbol", "symbol"]


def slugify(text: str) -> str:
    text = re.sub(r'[^\w\s-]', '', text.lower())
    text = re.sub(r'[\s_-]+', '_', text).strip('_')
    return text[:60]


def detect_symbol_col(header_row: list) -> int:
    """Return the column index most likely containing symbols."""
    for i, cell in enumerate(header_row):
        if cell and any(h in str(cell) for h in SYMBOL_COL_HINTS):
            return i
    # Default: column 1 (middle of No|Symbol|Desc)
    return 1


def crop_symbol(page_img, row_bbox, sym_col_bbox, padding: int = 4):
    """
    Crop the symbol cell from a rendered page image.

    page_img   : PIL Image of the rendered page
    row_bbox   : (x0, top, x1, bottom) in PDF pts (pdfplumber top-origin)
    sym_col_bbox: (x0, top, x1, bottom) column x-range in PDF pts
    """
    from PIL import Image

    # Convert PDF pts → pixels
    x0 = int(sym_col_bbox[0] * SCALE) - padding
    x1 = int(sym_col_bbox[2] * SCALE) + padding
    y0 = int(row_bbox[1] * SCALE) - padding
    y1 = int(row_bbox[3] * SCALE) + padding

    # Clamp to image bounds
    w, h = page_img.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)

    if x1 <= x0 or y1 <= y0:
        return None

    return page_img.crop((x0, y0, x1, y1))


def extract_table_symbols(
    pdf,
    table_id: str,
    pages: list[int],
    out_dir: Path,
    index: dict,
):
    """Extract all symbol images from a named table across its pages."""
    out_dir.mkdir(parents=True, exist_ok=True)

    row_counter = 0
    header_row = None

    for page_idx in pages:
        if page_idx >= len(pdf.pages):
            continue
        page = pdf.pages[page_idx]

        # Render page once
        pil_page = page.to_image(resolution=RESOLUTION).original

        ft_tables = page.find_tables()
        extracted_tables = [ft.extract() for ft in ft_tables]

        for ft, rows_data in zip(ft_tables, extracted_tables):
            if not rows_data or len(rows_data) < 2:
                continue

            # Detect header row
            first_row = rows_data[0]
            if any(cell and ('No' in str(cell) or 'Symbol' in str(cell) or 'Description' in str(cell))
                   for cell in first_row if cell):
                header_row = first_row
                data_start = 1
            else:
                data_start = 0

            sym_col = detect_symbol_col(header_row or [])

            # Get column x-boundaries from find_tables columns
            if sym_col < len(ft.columns):
                col_obj = ft.columns[sym_col]
                sym_col_x = (col_obj.bbox[0], col_obj.bbox[1], col_obj.bbox[2], col_obj.bbox[3])
            else:
                # Fallback: divide table width evenly
                tb = ft.bbox
                ncols = max(len(first_row), 3)
                col_w = (tb[2] - tb[0]) / ncols
                sym_col_x = (tb[0] + col_w * sym_col, tb[1],
                             tb[0] + col_w * (sym_col + 1), tb[3])

            for row_obj, row_data in zip(ft.rows[data_start:], rows_data[data_start:]):
                # Skip header-like rows
                if not row_data:
                    continue
                desc_cell = next(
                    (row_data[i] for i in range(len(row_data)-1, -1, -1)
                     if row_data[i] and str(row_data[i]).strip()),
                    ""
                )
                if not desc_cell or desc_cell.strip() in ('No', 'Symbol', 'Description'):
                    continue

                # Clean description for filename
                desc_clean = re.sub(r'\s+', ' ', str(desc_cell)).strip()
                # Take first non-empty fragment (split on bullets/newlines)
                fragments = [f.strip(' •–-') for f in re.split(r'[\n•]', desc_clean)]
                desc_short = next((f for f in fragments if len(f) > 3), desc_clean[:60])
                slug = slugify(desc_short) or f"row{row_counter}"
                fname = f"{row_counter:03d}_{slug}.png"

                # Crop symbol
                row_bbox = row_obj.bbox  # (x0, top, x1, bottom)
                img = crop_symbol(pil_page, row_bbox, sym_col_x)
                if img and img.width > 5 and img.height > 5:
                    fpath = out_dir / fname
                    img.save(str(fpath))
                    rel = f"isa5_1/symbols/{table_id}/{fname}"
                    index[rel] = desc_clean
                    row_counter += 1

    logger.info("Table %s: %d symbols extracted → %s", table_id, row_counter, out_dir)


def main():
    try:
        import pdfplumber
        from PIL import Image  # noqa: F401
    except ImportError as e:
        logger.error("Missing dependency: %s  (pip install pdfplumber Pillow)", e)
        sys.exit(1)

    if not PDF_PATH.exists():
        logger.error("PDF not found: %s", PDF_PATH)
        sys.exit(1)

    SYMBOL_DIR.mkdir(parents=True, exist_ok=True)
    index: dict[str, str] = {}

    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for table_id, pages in TARGET_TABLES.items():
            out_dir = SYMBOL_DIR / table_id
            extract_table_symbols(pdf, table_id, pages, out_dir, index)

    # Write index
    index_path = SYMBOL_DIR / "index.json"
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    logger.info("Total symbols: %d  →  index at %s", len(index), index_path)


if __name__ == "__main__":
    main()
