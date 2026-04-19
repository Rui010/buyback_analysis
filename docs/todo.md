# 改善TODO一覧

システム観点・業務観点でのコードレビューをもとにまとめた改善項目。

---

### [業務] 訂正と元データの紐付け
- **対象**: 設計書参照 → `docs/correction-link-design.md`
- **内容**: `corrections` テーブルが元のレコード（announcements/progress/completion）と紐付いておらず、分析時に手動照合が必要。LLMによる元文書種別の判定と、紐付けusecaseの追加で解決する

### [業務] 中期経営計画のデータ抽出
- **対象**: 設計書参照 → `docs/midterm_plan_design.md`
- **内容**: TDnetの「中期経営計画」「中経」「中計」を含むIRを取得し、GeminiでPDFから経営指標（売上高・営業利益率・ROE等）をJSON形式で抽出して `midterm_plans` テーブルに保存する。既存パイプラインとは分離した別エントリーポイント（`midterm_plan_analysis/main.py`）として実装する。

### [業務] 完了データの修正
- **対象**: `buyback_completion` テーブルの過去データ（`prompts/completion.md` は修正済み）
- **内容**: `start_date` / `end_date` の抽出対象を「全期間の累計取得実績」に修正したが（commit aa0bd97）、修正前に取り込まれた過去レコードは誤った値のまま残っている。バックフィル用スクリプトで対象URLを再取得・再抽出して上書きする必要がある。

### [業務] 発表データと完了データの結合による評価
- **対象**: `announcements` テーブル × `completion` テーブル（結合分析ビューまたはスクリプト）
- **内容**: 発表時に約束した自社株買い総数に満たないケースが多い、それを評価したい。`(code, resolution_date)` をキーに結合し、株数達成率（`shares_acquired / buyback_shares`）および金額達成率（`amount_spent_yen / buyback_amount_yen`）を算出する。

### [システム] RETIREMENT タイプの未実装
- **対象**: `buyback_analysis/consts/detect_type.py`（`DetectType.RETIREMENT`）
- **内容**: `DetectType` に `RETIREMENT`（自己株式消却）が定義されているが、対応するプロンプト（`prompts/retirement.md`）・ORMモデル・`post_data()` のマッピングが存在しない。現状は `ir_type.md` の判定でこのタイプが返された場合にエラーになる可能性がある。実装するか、対象外として `OTHER` 扱いにするか方針を決める必要がある。


