"""
Fetch the OnePetro E&P Glossary using Playwright (bypasses Cloudflare).

Usage:
    python -m scripts.fetch_onepetro_glossary

Output: data/raw/onepetro_glossary/onepetro_glossary.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Make the project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATA_DIR

_URL = "https://onepetro.org/pages/glossary"
_OUT_DIR = DATA_DIR / "onepetro_glossary"
_OUT_FILE = _OUT_DIR / "onepetro_glossary.json"


def fetch() -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        print(f"Fetching {_URL} ...")
        page.goto(_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        terms = page.evaluate("""
            var results = [];
            document.querySelectorAll('div.content p').forEach(p => {
                var termEl = p.querySelector('span.term a');
                if (!termEl) return;
                var termText = termEl.textContent.trim();
                var fullText = p.textContent.trim();
                var def = fullText.replace(termText, '').replace(/^[:\\s]+/, '').trim();
                results.push({term: termText, definition: def, href: termEl.href || ''});
            });
            results;
        """)
        browser.close()

    print(f"Extracted {len(terms)} terms")
    return terms


def main() -> None:
    terms = fetch()
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    _OUT_FILE.write_text(json.dumps(terms, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved to {_OUT_FILE}")


if __name__ == "__main__":
    main()
