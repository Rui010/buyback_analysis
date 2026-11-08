"""processing_runsのtoken・費用を文書（URL）単位で表示する（読み取りのみ）。

usage:
    python scripts/report_llm_usage.py [--since 2026-11-01] [URL ...]
"""

import argparse
import sys
from pathlib import Path

# ``python scripts/...`` でもリポジトリ直下のパッケージを解決できるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buyback_analysis.interface.sqlite_engine import SessionLocal
from tdnet_provenance.usecase.adopt_result import ensure_provenance_tables
from tdnet_provenance.usecase.aggregate_usage import aggregate_document_usage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", help="この日時以降に開始したrunだけを集計する（ISO8601）")
    parser.add_argument("urls", nargs="*")
    args = parser.parse_args()

    with SessionLocal() as session:
        ensure_provenance_tables(session)
        rows = aggregate_document_usage(session, urls=args.urls or None, since=args.since)

    total_in = total_out = 0
    total_cost = 0.0
    currencies = set()
    for row in rows:
        cost = f"{row['estimated_cost']} {row['currency']}" if row["currency"] else "未記録"
        print(f"{row['url']}  runs={row['runs']} {row['statuses']}  in={row['input_tokens']} "
              f"out={row['output_tokens']}  cost={cost}")
        total_in += row["input_tokens"]
        total_out += row["output_tokens"]
        total_cost += row["estimated_cost"]
        if row["currency"]:
            currencies.add(row["currency"])
    if len(currencies) > 1:
        raise SystemExit(f"通貨が混在しているため合計できません: {sorted(currencies)}")
    currency = next(iter(currencies), None)
    print(f"合計: 文書{len(rows)}件  in={total_in} out={total_out}  "
          f"cost={round(total_cost, 6)} {currency}" if currency else f"合計: 文書{len(rows)}件  in={total_in} out={total_out}  cost=未記録")


if __name__ == "__main__":
    main()
