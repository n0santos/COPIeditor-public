"""
Classify all in-scope clusters against the COPI scope definition.
Writes results to data/enrichment.db (cluster_scope table).
Run from project root: python -m scripts.classify_scope
"""

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
TERMS_DB      = ROOT / "data" / "terms.db"
ENRICHMENT_DB = ROOT / "data" / "enrichment.db"
API_URL       = "https://api.anthropic.com/v1/messages"
API_KEY       = os.environ["ANTHROPIC_API_KEY"]

EQUIPMENT_SOURCES = {"iso15926", "posc_caesar", "cfihos", "dexpi"}

SCOPE_DEF = (
    "COPI (Core Ontology for Petroleum Installations) scope: "
    "material artifacts (bfo:MaterialEntity) that (i) are part of a petroleum "
    "production plant, and (ii) bear at least one function whose realization "
    "involves the transport (e.g. production/injection lines), processing "
    "(e.g. separation, compression, heating), control, monitoring, measurement, "
    "containment or offloading of material or energy. "
    "OUT OF SCOPE: abstract quantities (wavelength, frequency, pressure as a concept), "
    "communication/IT equipment (telephone, computer, antenna) unless used for "
    "plant process control, office/building equipment, biological entities, "
    "activities, events, roles, organizations, documents, information objects, "
    "spatial locations, coding schemes, and anything not physically present in "
    "an oil & gas production plant."
)

BATCH_SIZE   = 80
CONCURRENCY  = 5


def get_in_scope_clusters() -> list[str]:
    tconn = sqlite3.connect(str(TERMS_DB))
    tconn.row_factory = sqlite3.Row
    rows = tconn.execute(
        "SELECT preferred_label, GROUP_CONCAT(DISTINCT source) as sources "
        "FROM terms GROUP BY preferred_label"
    ).fetchall()
    tconn.close()

    econn = sqlite3.connect(str(ENRICHMENT_DB))
    already_scoped = {
        r[0] for r in econn.execute("SELECT cluster_label FROM cluster_scope").fetchall()
    }
    econn.close()

    result = []
    for r in rows:
        if r["preferred_label"] in already_scoped:
            continue
        src_set = set((r["sources"] or "").split(","))
        has_equipment = bool(src_set & EQUIPMENT_SOURCES)
        if has_equipment:
            result.append(r["preferred_label"])
    return sorted(result)


def save_results(results: list[dict]) -> int:
    econn = sqlite3.connect(str(ENRICHMENT_DB))
    econn.execute("""
        CREATE TABLE IF NOT EXISTS cluster_scope (
            cluster_label TEXT PRIMARY KEY,
            out_of_scope  INTEGER NOT NULL DEFAULT 0,
            reason        TEXT DEFAULT '',
            updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    count = 0
    for item in results:
        label    = (item.get("label") or "").strip()
        in_scope = bool(item.get("in_scope", True))
        reason   = item.get("reason", "LLM classifier") or ""
        if not label:
            continue
        econn.execute("""
            INSERT INTO cluster_scope (cluster_label, out_of_scope, reason, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(cluster_label) DO UPDATE SET
                out_of_scope = excluded.out_of_scope,
                reason       = excluded.reason,
                updated_at   = excluded.updated_at
        """, (label, 0 if in_scope else 1, reason))
        count += 1
    econn.commit()
    econn.close()
    return count


async def classify_batch(
    client: httpx.AsyncClient,
    batch: list[str],
    sem: asyncio.Semaphore,
) -> list[dict]:
    items_text = "\n".join(f"{i+1}. {lbl}" for i, lbl in enumerate(batch))
    prompt = (
        f"{SCOPE_DEF}\n\n"
        "For each term below reply with ONLY a JSON array where each element is "
        '{"label": "...", "in_scope": true/false, "reason": "one sentence"}.\n\n'
        f"{items_text}"
    )

    async with sem:
        for attempt in range(3):
            try:
                resp = await client.post(
                    API_URL,
                    headers={
                        "x-api-key": API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 4096,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=60,
                )
                if resp.status_code == 429:
                    await asyncio.sleep(10 * (attempt + 1))
                    continue
                resp.raise_for_status()
                raw = resp.json()["content"][0]["text"]
                import re
                m = re.search(r"\[.*\]", raw, re.DOTALL)
                if not m:
                    print(f"  [warn] no JSON array in response for batch starting '{batch[0]}'")
                    return []
                return json.loads(m.group())
            except Exception as exc:
                print(f"  [error] attempt {attempt+1}: {exc}")
                await asyncio.sleep(5)
        return []


async def main() -> None:
    clusters = get_in_scope_clusters()
    total = len(clusters)
    print(f"Clusters to classify: {total}")
    if not total:
        print("Nothing to do.")
        return

    batches = [clusters[i:i+BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    print(f"Batches: {len(batches)} × up to {BATCH_SIZE} | concurrency: {CONCURRENCY}")

    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0
    oos_total = 0

    async with httpx.AsyncClient(timeout=90) as client:
        for i in range(0, len(batches), CONCURRENCY):
            chunk = batches[i:i+CONCURRENCY]
            tasks = [classify_batch(client, b, sem) for b in chunk]
            results_chunk = await asyncio.gather(*tasks)

            all_items: list[dict] = []
            for res in results_chunk:
                all_items.extend(res)

            saved = save_results(all_items)
            oos_batch = sum(1 for r in all_items if not r.get("in_scope", True))
            oos_total += oos_batch
            done += sum(len(b) for b in chunk)

            pct = done / total * 100
            print(f"  {done}/{total} ({pct:.0f}%)  —  {oos_batch} OOS this round  |  {oos_total} OOS total")

    print(f"\nDone. {oos_total} clusters marked out-of-scope.")


if __name__ == "__main__":
    asyncio.run(main())
