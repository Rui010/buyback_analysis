# 改善TODO一覧

システム観点・業務観点でのコードレビューをもとにまとめた改善項目。

---

## 優先度：今すぐ対応

### [システム] 文法エラーの修正
- **対象**: `buyback_analysis/usecase/detect_type.py`, `buyback_analysis/usecase/parse_text_by_llm.py`
- **内容**: `raise SystemExit("...") < e` という不正な構文を `raise SystemExit("...") from e` に修正
- **影響**: エラーチェーンが失われており、デバッグが困難

### [システム] `completion.py` の型定義の誤り
- **対象**: `buyback_analysis/models/completion.py`
- **内容**:
  - `shares_acquired = Column(Float)` → `Column(BigInteger)` に変更（整数であるべき値にFloat）
  - `buyback_method = Column(BigInteger)` → `Column(String)` に変更（文字列を格納しているのにBigInteger）

### [システム] `correction.py` が共有Baseを使っていない
- **対象**: `buyback_analysis/models/correction.py`
- **内容**: ファイル内で独自に `declarative_base()` を呼んでおり、`init_db()` でテーブルが正しく作成されないリスクがある
- **修正**: `from buyback_analysis.models.base import Base` に統一

---

## 優先度：近いうちに対応

### [システム] SQLインジェクション対策
- **対象**: `buyback_analysis/usecase/get_tdnet_buyback_data.py`
- **内容**: f-string でSQL文字列を直接組み立てている。SQLAlchemy の `text()` とパラメータバインドに変更する
- **例**:
  ```python
  # 現状（危険）
  query = f"WHERE date <= '{end_date}' AND date >= '{start_date}'"

  # 修正後
  from sqlalchemy import text
  query = text("WHERE date <= :end AND date >= :start")
  conn.execute(query, {"end": end_date, "start": start_date})
  ```

### [システム] LLM出力のバリデーション追加
- **対象**: `buyback_analysis/usecase/parse_text_by_llm.py`, `buyback_analysis/usecase/post_data.py`
- **内容**: LLMが返したJSONをそのままDBに保存しており、`code` や `disclosure_date` が `null` のまま保存されうる。必須フィールドのnullチェックを追加する

### [システム] セッションが例外時にクローズされない
- **対象**: `buyback_analysis/main.py`
- **内容**: 処理途中で例外が起きると `session.close()` が呼ばれない。`try/finally` で囲む

### [システム] ログと `print()` の混在を解消
- **対象**: `buyback_analysis/main.py`, `buyback_analysis/usecase/get_pdf_data.py`
- **内容**: `print()` と `logger` が混在している。すべて `logger` に統一する

### [システム] ロガー変数名の衝突
- **対象**: `buyback_analysis/usecase/detect_type.py`, `buyback_analysis/usecase/get_tdnet_buyback_data.py`
- **内容**: `logging = Logger()` という変数名が Python 標準ライブラリ `logging` と衝突する。`logger` に変更する

### [システム] 重複インポートの削除
- **対象**: `buyback_analysis/main.py`
- **内容**: `from buyback_analysis.usecase.logger import Logger` が2回インポートされている（L8, L19）

---

## 優先度：余裕があれば対応

### [業務] データ取得期間の柔軟化
- **対象**: `buyback_analysis/main.py`
- **内容**: PostgreSQLからの取得期間が「過去5日」にハードコードされている。障害時や初期投入時に対応できるよう、開始日・終了日を引数または環境変数で指定できるようにする

### [業務] 訂正と元データの紐付け
- **対象**: 設計書参照 → `docs/correction-link-design.md`
- **内容**: `corrections` テーブルが元のレコード（announcements/progress/completion）と紐付いておらず、分析時に手動照合が必要。LLMによる元文書種別の判定と、紐付けusecaseの追加で解決する

### [業務] 処理サマリーのログ出力
- **対象**: `buyback_analysis/main.py`
- **内容**: 毎回の実行で「何件処理・何件成功・何件スキップ・何件失敗」のサマリーが出ない。日次確認のためにカウンターを追加してログ出力する

### [業務] `resolution_date` を主キーに含めることの検討
- **対象**: `buyback_analysis/models/completion.py`, `buyback_analysis/models/announcement.py`
- **内容**: 同一企業・同日に複数の自社株買いを決議するケースで主キー衝突が起きる可能性がある。`resolution_date` を複合主キーに加えることを検討

### [システム] テストの導入
- **対象**: プロジェクト全体
- **内容**: ユニットテスト・統合テストが存在しない。Gemini API・PDFダウンロード・DBアクセスをモック化した `pytest` ベースのテストを整備する
