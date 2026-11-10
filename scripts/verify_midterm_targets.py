"""中計目標の抽出を、本番DBに書き込まずに正解データ（ir-analytics-platformの原典確認）と突き合わせる。

引継ぎ仕様（ir-analytics-platform docs/plans/handoffs/buyback-midterm-target-extraction.md）第8節の
「本番DBに書き込まないローカルの実行」用。main.pyと同じ経路（prepare_pdf_input・run_midterm_metrics・
determine_midterm_status）で抽出し、SQLiteにもprocessing_runにも書かない。実LLMを呼ぶ
（metricsは1文書1回、metricsが空ならclassificationを1回）。

使い方:
    python -m scripts.verify_midterm_targets --out <出力フォルダ>
    python -m scripts.verify_midterm_targets --out <出力フォルダ> --compare-only   # LLMを呼ばず保存済み結果で再判定

出力: <出力フォルダ>/results.json（文書ごとの抽出結果・token数・判定）、report.md（条件ごとの結果）
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from buyback_analysis.interface.llm_usage import capture_llm_usage
from buyback_analysis.interface.postgresql_engine import get_database_engine
from midterm_plan_analysis.usecase.compare_midterm_fixture import compare_document, summarize
from midterm_plan_analysis.usecase.determine_midterm_status import determine_midterm_status
from midterm_plan_analysis.usecase.get_tdnet_midterm_data import get_tdnet_midterm_data_by_urls
from midterm_plan_analysis.usecase.run_midterm_stages import (
    METRICS_PROMPT_NATIVE,
    METRICS_PROMPT_TEXT,
    run_midterm_classification,
    run_midterm_metrics,
)
from tdnet_provenance.usecase.prepare_pdf_input import prepare_pdf_input
from tdnet_provenance.usecase.provenance_recorder import prompt_file_hash

DEFAULT_FIXTURE = r"C:\apps\ir-analytics-platform\fixtures\phase-2.5\midterm-source-review.json"
CONDITION_TITLES = {
    "1": "全社目標がmetricsにあり値・単位・期末が一致",
    "2": "計画期間外の目標がtarget_scope=long_term",
    "3": "見直し前の目標がrevision_role=previous",
    "4": "業績予想・実績・見込がmetricsに入っていない",
    "5": "目標表に並ぶ値がreference_valuesにありkindが一致",
    "6": "8185の連結・単体がconsolidation_labelで区別",
    "7": "1814・4042の全社目標にsegmentなし",
    "8": "撤回・延期のextraction_statusが従来どおり",
}


def _sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def extract(fixture: dict, use_native: bool, pdf_root: str) -> list[dict]:
    documents = fixture["documents"]
    rows = get_tdnet_midterm_data_by_urls(engine=get_database_engine(), urls=[d["url"] for d in documents])
    rows_by_url = {row["link"]: row for _, row in rows.iterrows()}
    results = []
    for doc in documents:
        row = rows_by_url.get(doc["url"])
        entry = {"security_code": doc["security_code"], "disclosure_date": doc["disclosure_date"], "url": doc["url"]}
        results.append(entry)
        if row is None:
            entry["error"] = "tdnetに行がない"
            continue
        title, code, name = row["title"], str(row["code"]), row["name"]
        entry["title"] = title
        pdf_input = prepare_pdf_input(
            None, url=doc["url"], disclosure_date=row["date"], time=row["time"],
            pud_date_str=row["date"].strftime("%Y%m%d"), pdf_root=pdf_root,
            use_native=use_native, stage="metrics", page_markers=True,
        )
        if pdf_input is None:
            entry["error"] = "PDFの取得に失敗"
            continue
        if pdf_input.pdf_path is not None:
            entry["sha256_matches_fixture"] = _sha256(pdf_input.pdf_path) == doc["sha256"]

        calls = [1]  # metrics（Geminiの応答にrequest IDがないため呼び出しを自前で数える）

        def classify():
            calls[0] += 1
            return run_midterm_classification(None, pdf_input, title=title, code=code, name=name)

        with capture_llm_usage() as usage:
            result = run_midterm_metrics(None, pdf_input, title=title, code=code, name=name)
            status = "failed" if result is None else determine_midterm_status(
                title, result.get("data", {}).get("metrics"), classify=classify,
            )
        entry.update(
            result=result, extraction_status=status, llm_calls=calls[0],
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
        )
        print(f"{code} {doc['disclosure_date']} status={status} calls={calls[0]} "
              f"tokens={usage.input_tokens}/{usage.output_tokens}")
    return results


def compare(fixture: dict, results: list[dict]) -> list[dict]:
    by_url = {r["url"]: r for r in results}
    for doc in fixture["documents"]:
        entry = by_url[doc["url"]]
        entry["comparison"] = compare_document(doc, entry.get("result"), entry.get("extraction_status"))
    return results


def write_report(path: Path, results: list[dict], meta: dict) -> None:
    total = summarize(results)
    lines = ["# 中計目標抽出のローカル検証", ""]
    lines += [f"- {key}: {value}" for key, value in meta.items()]
    calls = sum(r.get("llm_calls", 0) for r in results)
    tokens_in = sum(r.get("input_tokens", 0) for r in results)
    tokens_out = sum(r.get("output_tokens", 0) for r in results)
    lines += [f"- LLM呼び出し: {calls}回、token 入力{tokens_in:,} / 出力{tokens_out:,}", ""]
    lines += ["| # | 条件 | 判定数 | 不一致 |", "|---|---|---:|---:|"]
    lines += [f"| {n} | {CONDITION_TITLES[n]} | {t['checked']} | {t['failed']} |" for n, t in total.items()]
    for r in results:
        lines += ["", f"## {r['security_code']} {r['disclosure_date']} {r.get('title', '')}", ""]
        if r.get("error"):
            lines.append(f"- エラー: {r['error']}")
            continue
        lines.append(f"- extraction_status: {r.get('extraction_status')}、PDFのhash一致: {r.get('sha256_matches_fixture')}")
        comparison = r["comparison"]
        for number, condition in comparison["conditions"].items():
            for failure in condition["failures"]:
                lines.append(f"- 条件{number} 不一致: {failure}")
        for note in comparison["notes"]:
            lines.append(f"- 補足: {note}")
        for extra in comparison["unmatched_company_metrics"]:
            lines.append(f"- 正解データにない全社目標: {extra}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default=DEFAULT_FIXTURE)
    parser.add_argument("--out", required=True, help="結果の出力フォルダ")
    parser.add_argument("--compare-only", action="store_true", help="LLMを呼ばずresults.jsonを再判定する")
    args = parser.parse_args()

    load_dotenv()
    use_native = os.getenv("MIDTERM_USE_NATIVE_PDF", "false").lower() == "true"
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results_path = out / "results.json"

    if args.compare_only:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    else:
        results = extract(fixture, use_native, os.getenv("PDF_DOWNLOAD_PATH"))
    results = compare(fixture, results)
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    prompt = METRICS_PROMPT_NATIVE if use_native else METRICS_PROMPT_TEXT
    meta = {"方式": "native" if use_native else "text", "プロンプト": prompt, "プロンプトhash": prompt_file_hash(prompt)}
    write_report(out / "report.md", results, meta)
    for number, total in summarize(results).items():
        print(f"条件{number}: {total['checked'] - total['failed']}/{total['checked']}")


if __name__ == "__main__":
    main()
