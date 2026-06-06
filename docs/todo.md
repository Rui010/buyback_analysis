# 改善TODO一覧

システム観点・業務観点でのコードレビューをもとにまとめた改善項目。

---

### [業務] 訂正と元データの紐付け・修正適用
- **対象**: 設計書参照 → `docs/correction-link-design.md`
- **内容**: `corrections` テーブルの紐付けと元レコードへの修正適用を実装する。以下の順で作業する。

#### 実装タスク

**1. DB スキーマ変更**
- [ ] `corrections` モデル（`models/correction.py`）に以下のカラムを追加
  - `linked_table` (String, nullable) ― 紐付け先テーブル名
  - `linked_record_url` (String, nullable) ― 紐付け先レコードの URL
  - `linked` (Boolean, default=False)
  - `applied` (Boolean, default=False)
- [ ] `models/progress.py` に `status` カラム追加（`AnnouncementStatus` Enum 流用）
- [ ] `models/completion.py` に `status` カラム追加（同上）
- [ ] `interface/sqlite_engine.py` の `init_db()` でマイグレーション対応（Alembic or `CREATE TABLE IF NOT EXISTS` 相当）

**2. プロンプト作成**
- [ ] `prompts/link_corrections.md` を新規作成
  - 入力：当日の訂正一覧（id / document_title / original_announcement_date / code）＋企業別IR候補一覧
  - 出力：`[{correction_id, linked_table, linked_record_url}]` の JSON
- [ ] `prompts/apply_correction.md` を新規作成
  - 入力：元レコードの現在値（フィールド名: 値）＋変更のある corrections エントリ＋更新可能フィールド一覧
  - 出力：`{field_name: new_value, ...}` の JSON（変更フィールドのみ）

**3. usecase 実装**
- [ ] `usecase/link_corrections_by_llm.py` を新規作成
  - 当日の `corrections` レコードを取得
  - 各企業の直近1年分 IR 一覧（announcements / progress / completion）を取得
  - LLM で紐付けを実行
  - `corrections.linked_table` / `linked_record_url` / `linked` を更新
  - 元レコードの `status → has_correction` を更新
- [ ] `usecase/apply_corrections_by_llm.py` を新規作成
  - `linked=True, applied=False` のレコードを1件ずつ処理
  - `before_text == after_text` のエントリを除外してLLMに渡す
  - LLM が返すパッチを元レコードに適用
  - 元レコードの `status → corrected`、`corrections.applied → True` を更新

**4. main.py への組み込み**
- [ ] 全件ループ完了後に `link_corrections_by_llm(session, target_date)` を呼び出す
- [ ] その後 `apply_corrections_by_llm(session)` を呼び出す

**5. 既存データ移行スクリプト**
- [ ] `scripts/migrate_corrections.py` を新規作成
  - 開示日ごとにグループ化して `link_corrections_by_llm()` を順次実行
  - 紐付け完了後に `apply_corrections_by_llm()` を実行

### [業務] 中期経営計画のデータ抽出
- **対象**: 設計書参照 → `docs/midterm_plan_design.md`
- **内容**: TDnetの「中期経営計画」「中経」「中計」を含むIRを取得し、GeminiでPDFから経営指標（売上高・営業利益率・ROE等）をJSON形式で抽出して `midterm_plans` テーブルに保存する。既存パイプラインとは分離した別エントリーポイント（`midterm_plan_analysis/main.py`）として実装する。

### ~~[業務] 完了データの修正~~ ✅ 完了
- 設計書: `docs/backfill-completion-design.md`
- 実装: `scripts/backfill_completion.py`（`python scripts/backfill_completion.py` で実行）

### [システム] post_data.py のrowデータ受け取りリファクタリング
- **対象**: `buyback_analysis/usecase/post_data.py`
- **内容**: `code` / `url` / `disclosure_date` をLLM出力（`data["data"]`）に依存するのではなく、`post_midterm_plan.py` と同様にrowデータから引数として受け取るよう変更する。LLMが返す値の信頼性を下げ、入力元を明確に分離する。

### [業務] 発表データと完了データの結合による評価
- **対象**: `announcements` テーブル × `completion` テーブル（結合分析ビューまたはスクリプト）
- **内容**: 発表時に約束した自社株買い総数に満たないケースが多い、それを評価したい。`(code, resolution_date)` をキーに結合し、株数達成率（`shares_acquired / buyback_shares`）および金額達成率（`amount_spent_yen / buyback_amount_yen`）を算出する。

### ~~[システム] RETIREMENT タイプの未実装~~ ✅ 完了
- `models/retirement.py`・`prompts/retirement.md`・`post_data()` マッピング・`main.py` の対象タイプ追加を実装済み。


