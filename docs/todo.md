# 改善TODO一覧

システム観点・業務観点でのコードレビューをもとにまとめた改善項目。

---

### [業務] 訂正と元データの紐付け
- **対象**: 設計書参照 → `docs/correction-link-design.md`
- **内容**: `corrections` テーブルが元のレコード（announcements/progress/completion）と紐付いておらず、分析時に手動照合が必要。LLMによる元文書種別の判定と、紐付けusecaseの追加で解決する

### [業務] 中期経営計画のデータ抽出
- **対象**: 設計書参照 → `docs/midterm_plan_design.md`
- **内容**: TDnetの「中期経営計画」「中経」「中計」を含むIRを取得し、GeminiでPDFから経営指標（売上高・営業利益率・ROE等）をJSON形式で抽出して `midterm_plans` テーブルに保存する。既存パイプラインとは分離した別エントリーポイント（`midterm_plan_analysis/main.py`）として実装する。

### ~~[業務] 完了データの修正~~ ✅ 完了
- 設計書: `docs/backfill-completion-design.md`
- 実装: `scripts/backfill_completion.py`（`python scripts/backfill_completion.py` で実行）

### [業務] 発表データと完了データの結合による評価
- **対象**: `announcements` テーブル × `completion` テーブル（結合分析ビューまたはスクリプト）
- **内容**: 発表時に約束した自社株買い総数に満たないケースが多い、それを評価したい。`(code, resolution_date)` をキーに結合し、株数達成率（`shares_acquired / buyback_shares`）および金額達成率（`amount_spent_yen / buyback_amount_yen`）を算出する。

### ~~[システム] RETIREMENT タイプの未実装~~ ✅ 完了
- `models/retirement.py`・`prompts/retirement.md`・`post_data()` マッピング・`main.py` の対象タイプ追加を実装済み。


