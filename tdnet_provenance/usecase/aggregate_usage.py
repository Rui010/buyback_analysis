"""processing_runsのtoken・費用を文書（URL）単位で集計する（tdnet-provenance-v1 Step 3）。

再利用runはtoken・費用0で記録されているため、そのまま合計すると新規LLM実行分だけになる。
"""

from collections import defaultdict

from tdnet_provenance.models.processing_run import ProcessingRun


def aggregate_document_usage(session, *, urls=None, since: str | None = None) -> list[dict]:
    """URLごとの {url, runs, statuses, input_tokens, output_tokens, estimated_cost, currency} を返す。

    since（ISO8601の日付・時刻）以降に開始したrunだけを対象にできる。費用が未記録のrunは
    費用合計に含めない（cost_missing_runsで件数を返す）。1つのURLで通貨が混在したらValueError。
    """
    query = session.query(ProcessingRun)
    if urls:
        query = query.filter(ProcessingRun.url.in_(list(urls)))
    if since:
        query = query.filter(ProcessingRun.started_at >= since)

    grouped = defaultdict(list)
    for run in query.all():
        grouped[run.url].append(run)

    results = []
    for url, runs in sorted(grouped.items(), key=lambda item: item[0] or ""):
        currencies = {
            r.estimated_cost_currency for r in runs
            if r.estimated_cost_currency and r.estimated_cost is not None  # 0円の再利用runも通貨を持つ
        }
        if len(currencies) > 1:
            raise ValueError(f"通貨が混在しているため費用を合計できません: {url} {sorted(currencies)}")
        statuses = defaultdict(int)
        for r in runs:
            statuses[r.status] += 1
        results.append({
            "url": url,
            "runs": len(runs),
            "statuses": dict(statuses),
            "input_tokens": sum(r.input_tokens or 0 for r in runs),
            "output_tokens": sum(r.output_tokens or 0 for r in runs),
            "estimated_cost": round(sum(r.estimated_cost or 0 for r in runs), 6),
            "currency": next(iter(currencies), None),
            "cost_missing_runs": sum(
                1 for r in runs if r.run_kind == "extract" and r.status in {"succeeded", "failed"}
                and r.input_tokens is not None and r.estimated_cost is None
            ),
        })
    return results
