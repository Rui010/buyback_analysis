# 中計目標の重複候補（possible_duplicate_target）のレビュー用JSON：引継ぎ

作成日: 2026-11-13
対象commit: `316b399`（検出・JSON出力）、`b319134`（取込みを外し、出力先を既定化）
状態: 実装・テスト済み。**本番ではまだ実行していない**（本番SQLiteから出したJSONはまだない）

## 1. 決めたこと

- buyback_analysisは、中計の`metrics`から「同じ期の同じ目標かもしれないが、断定できない別ページの2行」を見つけ、レビュー用JSONに出す。LLMは追加で呼ばない
- **SQLite（`midterm_plans`）はLLMの抽出結果のまま変えない**。期末まで同じ明確な重複は、これまでどおり正規化で自動統合する。それ以外の候補は削除しない
- **どれが本当の重複かの判断と手修正は、下流（PostgreSQL側・ir-analytics-platform）で行う**。手修正をbuyback_analysisのSQLiteへ取り込む仕組みは作らない（一度作ったが`b319134`で外した）

依頼のきっかけは5367（2025-05-01）。p.1「2031年3月期（計画）」とp.10「2030年度」に同じ売上高13,000百万円・営業利益1,940百万円があり、p.10側の期末がnullのときに2行になる。今回の検出で、この2組がそれぞれ1件の候補になる。

## 2. 下流にお願いしたいこと

1. **手修正は修正用の仕組みで持つ**: `buyback_midterm_plans`はSQLiteからの同期コピーのため、直接直すと次の同期で上書きされうる（同期の挙動はbuyback_app側で要確認）。修正は別の仕組み（例: 修正用テーブル）で持ち、読むときに重ねる形を想定している
2. **修正が古くなったら使わない**: 修正には、JSONの`adopted_version_id`・`source_hash`・`candidate_id`を一緒に控える。再抽出（RERUN）などで採用版が変わると、`adopted_version_id`が変わる。現在の値と一致しない修正は自動で使わず、最新データでレビューし直す
3. **JSONの受け渡し方法を決める**: 当面は、buyback_analysis側で必要なときにスクリプトを実行し、JSONファイルを渡す手動運用を想定している。下流がPostgreSQLから自分で同じ判定をしたい場合は、採用version ID・source hashがPostgreSQL側にあるかの確認が必要

## 3. JSONの出し方

サーバー（またはUNCパス経由）で実行する。SQLiteは読み取り専用で開き、何も書かない。

```powershell
.\.venv\Scripts\python.exe -m scripts.review_midterm_duplicate_candidates --db-path \\100.64.1.30\dq-c\sqlite_db\buyback.db
# → \\100.64.1.30\dq-c\sqlite_db\midterm_duplicate_review\review_<日時>.json
```

- `--out`で出力先を指定できる。省略時は、SQLiteと同じ場所の`midterm_duplicate_review/review_<ローカル日時>.json`
- `--urls <URL>,<URL>`で文書を絞れる。省略時は`extraction_status=ok`の全文書を見て、候補のある文書だけを出す
- 日次パイプラインも、候補を見つけると`midterm_plan_analysis.log`に`[REVIEW] possible_duplicate_target`ログを出す（JSONは出さない）

## 4. 候補の条件

次をすべて満たす2行の組（`midterm_plan_analysis/usecase/detect_duplicate_candidates.py`、`midterm_duplicate_detector:1`）。

- 指標名・`value`（null以外）・単位・`segment`・`consolidation_label`・`revision_role`・`target_scope`・`bound`・`value_upper`が同じ
- 両方の`page`が分かっていて、別のページにある
- `target_period_label`か`target_fiscal_end`が違う
- 期末・期間ラベルから読める期末の西暦年が重なるか、どちらかが読めない。「2031年3月期」は2031年、「2030年度」「FY2030」は2030年か2031年とみなす。年が重ならない組（ROE 10%以上が「2029年3月期」と「2030年3月期」に並ぶなど）は、別の目標として候補にしない

検知理由`reasons`は、次の期末の状態のいずれか1つ。

| 値 | 意味 |
|---|---|
| `fiscal_end_missing_one_side` | 期末が片方だけnull（5367のケース） |
| `fiscal_end_missing_both` | 期末が両方null |
| `fiscal_end_differs` | 期末が違う |
| `same_fiscal_end_not_merged` | 期末が同じなのに統合されていない（正規化v2より前に保存された行） |

ラベルが違う場合は、これに`period_label_differs`が加わる。

## 5. JSONの形（`format_version=1`）

```json
{
  "kind": "midterm_duplicate_review", "format_version": 1, "detector_version": "midterm_duplicate_detector:1",
  "generated_at": "2026-11-13T06:30:00+00:00", "instructions": "...",
  "entries": [{
    "url": "...", "code": "5367", "disclosure_date": "2025-05-01", "extraction_status": "ok",
    "adopted_version_id": "...", "version_origin": "run", "source_hash": "...",
    "run_ids": ["..."], "prompt_name": "midterm_plan_native.md", "prompt_hash": "...",
    "result": {"type": "MIDTERM_PLAN", "data": {"plan_name": "...", "metrics": [], "reference_values": []}},
    "candidates": [{
      "kind": "possible_duplicate_target", "candidate_id": "...", "metric_indexes": [0, 3], "pages": [1, 10],
      "reasons": ["fiscal_end_missing_one_side", "period_label_differs"], "detail": "...",
      "rows": [{}, {}], "resolution": null
    }]
  }]
}
```

| 項目 | 内容 |
|---|---|
| `adopted_version_id` | `result_adoptions`の最新の採用version。採用記録がない文書（provenance導入前のまま再抽出していない行）はnull |
| `version_origin` | 採用版の由来（`run`・`unrecorded`・`legacy`）。採用記録がなければnull |
| `source_hash` | `tdnet_source_documents`のPDFのSHA-256。台帳未登録ならnull |
| `prompt_name`・`prompt_hash` | 採用版のmetrics stageのrunの値。run記録のない版（`unrecorded`・`legacy`）はnull。サーバーのチェックアウトはCRLFのため、開発PCで計算したhashとは違う |
| `result` | その時点の採用行（`midterm_plans`）の内容 |
| `candidates[].metric_indexes` | `result.data.metrics`内の位置（0始まり） |
| `candidates[].rows` | 候補の2行の全フィールド |
| `candidates[].candidate_id` | 組の2行の識別項目から作るID。行の順序・metrics内の位置・`value_text`には依らない。同じ2行なら、次回のJSONでも同じIDになる |
| `candidates[].resolution` | 常にnullで出力する。下流で`merged`（同じ目標）か`distinct`（別の目標）を記録する欄 |

## 6. 注意点・未決事項

- **ページ番号のない行は検出されない**: ページの目印を入れる前のtext方式で抽出した行は、`page`がnullのため対象外
- **`distinct`の判断はbuyback_analysis側に残らない**: 次回のJSONにも同じ候補（同じ`candidate_id`）が出る。判断済みかどうかは下流で`candidate_id`を使って管理してほしい
- **本番での件数は未確認**: 候補が何件あるかはまだ分からない。必要なら最初のJSONを出して件数を共有する
- **同期の上書き**: `buyback_midterm_plans`が同期で上書きされるかは未確認（2-1）

## 7. 参照

- 設計: `docs/midterm_plan_design.md`「重複候補のレビュー」
- 検出: `midterm_plan_analysis/usecase/detect_duplicate_candidates.py`
- JSONの作成: `midterm_plan_analysis/usecase/review_duplicate_candidates.py`、`scripts/review_midterm_duplicate_candidates.py`
- テスト: `tests/midterm_plan_analysis/usecase/test_detect_duplicate_candidates.py`、`test_review_duplicate_candidates.py`、`tests/scripts/test_midterm_duplicate_review_flow.py`
