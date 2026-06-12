# buyback_analysis パイプライン 課題整理

> 作成: 2026-06-12  
> 対象セッションのきっかけ: `is_checked.parse_status = 'failed'` が 448 件あり、再取り込みを試みた際に複数の問題が顕在化した。

---

## 目次

1. [実施済みの変更](#実施済みの変更)
2. [Issue A: ToSTNeT-3 2枚セット問題（UNIQUE制約）](#issue-a-tostnet-3-2枚セット問題unique制約)
3. [Issue B: PDF取得失敗 214件（上場廃止等）](#issue-b-pdf取得失敗-214件上場廃止等)
4. [Issue C: テキストパース失敗 → ネイティブPDFフォールバック](#issue-c-テキストパース失敗--ネイティブpdfフォールバック)
5. [Issue D: NOT NULL制約失敗 11件](#issue-d-not-null制約失敗-11件)
6. [Issue E: モデル/DBスキーマ不一致](#issue-e-モデルdbスキーマ不一致)
7. [未解決タスク一覧](#未解決タスク一覧)

---

## 実施済みの変更

| コミット | 内容 |
|---------|------|
| `9735136` | `ir_type.md`: 「他社の自己株取得への応募」を `other` に分類するよう明示 |
| `9735136` | `completion.md`: ToSTNeT-3形式の抽出ガイドを追加、除外チェックを最優先化 |
| `2c0e93d` | `main.py`: 対象外スキップ時のログレベルを `error` → `info` に変更 |
| `a205103` | `main.py`: `is_checked` を PDFダウンロード前に確認する事前チェック追加（不要なダウンロード回避） |
| `305e001` | `main.py`: テキストパース失敗時にネイティブPDFでリトライするフォールバック処理追加 |
| `a266e46` | `main.py`: `_needs_native_fallback()` ヘルパーと `REQUIRED_FIELDS` 定義追加 |
| (未コミット) | `ir_type.md`: ToSTNeT-3実績文書を `buyback_completion` に分類するよう明示。複合文書（「取得及びToSTNeT-3」）は `buyback_announcement` とする旨も追記 |

### 生成済み作業ファイル（`logs/` に退避済み）

| ファイル | 内容 |
|---------|------|
| `logs/insert_skipped.sql` | 214件の上場廃止URLを `is_checked` に `skipped` として INSERT するSQL（**実行済み**） |
| `logs/pdf_download_failures.csv` | PDF取得失敗URL一覧（650件）|
| `logs/downloaded_files.txt` | 手動ダウンロードできたPDFのファイル一覧 |
| `logs/skipped_comparison.csv` | UNIQUE制約スキップ102件のログ値 vs PostgreSQL値の比較結果 |
| `logs/migrate_tostnet_to_completion.sql` | 誤保存247件を `announcements` から削除し `is_checked` を `failed` にリセットするSQL（**実行済み**） |
| `logs/gen_migrate_sql.py` | 上記SQLを PostgreSQL から再生成するスクリプト |

---

## Issue A: ToSTNeT-3 2枚セット問題（UNIQUE制約）

### 概要

ToSTNeT-3（立会外買付）を実施した企業は、**同じ開示日に2種類のPDFをTDnetに提出**する。

| PDF | タイトル例 | 内容 |
|-----|-----------|------|
| ① 取締役会決議 | 「自己株式取得に係る事項の決定に関するお知らせ」 | 取得上限（計画値）。金額・株数が大きい |
| ② ToSTNeT-3結果 | 「自己株式立会外買付取引（ToSTNeT-3）による自己株式の買付けに関するお知らせ」 | 当日朝の実際取得結果。金額・株数が小さい |

両PDFは `(code, disclosure_date)` が同一なので、2枚目を保存しようとすると UNIQUE制約エラーになる。

### 調査結果

- UNIQUE制約でスキップされたレコード: **102件**
- うちログ値とPostgreSQL値が**異なるもの: 77件**（77%）
- 値が一致するもの: 25件（同内容の別URLによる重複）

**差異の典型例（6535 / 2025-06-11）：**

| | 金額 | 株数 |
|-|------|------|
| DB（先に処理） | 6億円 | 102万株 | → ToSTNeT-3実績 |
| Log（後にブロック） | 12億円 | 180万株 | → 取締役会決議（上限） |

### 例外パターン

| code | 内容 | 本来の分類 |
|------|------|-----------|
| 4475 | 「（訂正）自己株式の取得状況」| `correction` として別保存すべき |
| 3626 | 訂正 + 補足説明資料 | 同上 |
| 8560 | 訂正 | 同上 |
| 6902, 7259 | 「公開買付け実施に向けた進捗状況」 | スキップ可 |
| 8630 | J-ESOP（株式報酬）PDF | `equity_compensation` |
| 9980 | 「取得事項の一部変更」 | 内容変更通知、別処理が必要 |

### 根本原因

LLM が ToSTNeT-3 実績PDFを `buyback_announcement` と誤分類しているため、取締役会決議と同じ `buyback_announcements` テーブルに保存しようとして UNIQUE制約 `(code, disclosure_date)` に衝突している。

### 方針（決定）

**ToSTNeT-3 実績PDFを `buyback_completion` として正しく分類する。**

| PDF | 正しい分類 | 保存先テーブル |
|-----|-----------|--------------|
| 「自己株式取得に係る事項の決定に関するお知らせ」（取締役会決議） | `buyback_announcement` | `buyback_announcements` |
| 「ToSTNeT-3による自己株式の買付けに関するお知らせ」（実績報告） | `buyback_completion` | `buyback_completion` |

異なるテーブルに保存されるため、**スキーマ変更不要・UNIQUE制約の衝突も発生しない**。

### 必要な実装

1. ✅ **`ir_type.md` の修正**: ToSTNeT-3 実績文書（実際の取得株数・金額が記載）を `buyback_completion` に分類するよう明示。複合文書（「取得及びToSTNeT-3」）は `buyback_announcement` とする旨も追記。
2. **`is_checked` の `failed` レコード再処理**: 再分類により正しいテーブルに保存される
3. **過去に `buyback_announcements` に誤保存されたToSTNeT-3実績レコードの移行**: `logs/migrate_tostnet_to_completion.sql` を SQLite で実行（**247件・未実行**）

### 移行手順

```bash
# 1. migration SQL を SQLite に適用
sqlite3 data.db < logs/migrate_tostnet_to_completion.sql

# 2. is_checked の failed 件数を確認
sqlite3 data.db "SELECT COUNT(*) FROM is_checked WHERE parse_status='failed';"

# 3. パイプラインを再実行（failed レコードが buyback_completion として再保存される）
python -m buyback_analysis.main
```

### 残課題（複合文書 335件）

「取得及びToSTNeT-3による買付け」タイプの複合文書（現在 `buyback_announcements` に335件）は、取締役会決議の情報（上限金額・株数・期間）を含むため `buyback_announcement` として保存されているのは正しい分類。ただし、LLM がToSTNeT-3実績の数値（小さい値）を誤って抽出している可能性がある。別途バリデーション・再処理が必要かどうかを要検討。

---

## Issue B: PDF取得失敗 214件（上場廃止等）　✅ 対応済み

### 概要

TDnetに登録されているURLのPDFが存在しない（上場廃止等でサーバーから削除済み）。

- 全PDF取得失敗: **650件**
- うち手動ダウンロードが確認できなかった（本当に存在しない）: **214件**

### 問題

パイプラインは PDFダウンロード失敗時に `post_url()` を呼ばないため、これらのURLは `is_checked` に未登録。毎回ダウンロード試行が発生する。

### 対応（完了）

1. `logs/insert_skipped.sql` を実行し、214件を `is_checked` に `skipped` として登録済み。
2. `main.py` の事前チェック（コミット `a205103`）により、再試行しない。

---

## Issue C: テキストパース失敗 → ネイティブPDFフォールバック

### 概要

pypdf でテキスト抽出できないエンコーディング（`/UniJIS-UTF16-H`、`/90ms-RKSJ-H` 等）を含むPDFがある。
また、テキスト抽出できても LLM が必須フィールドを null で返すケースがある。

### 対応（実装済み）

`main.py` に `_needs_native_fallback()` を追加し、以下の条件を満たす場合にネイティブPDF（バイナリ）で Gemini に再送信する：

```python
REQUIRED_FIELDS = {
    DetectType.BUYBACK_COMPLETION: ["shares_acquired", "amount_spent_yen"],
}

def _needs_native_fallback(obj, detect_type_enum):
    if obj is None or obj.get("data") is None:
        return True  # テキスト抽出自体が失敗
    for field in REQUIRED_FIELDS.get(detect_type_enum, []):
        if data.get(field) is None:
            return True  # 必須フィールドが null
    return False
```

### 残課題

- `REQUIRED_FIELDS` は現在 `buyback_completion` のみ定義。他の種別も必要に応じて追加を検討。
- フォールバック後もパース失敗するケース（29件）は手動対応が必要。

---

## Issue D: NOT NULL制約失敗 11件

### 概要

LLMのパース結果を保存しようとした際に NOT NULL制約に違反し、**`is_checked.parse_status = 'saved'` になっているが実際にはデータが未保存**なレコードが 11件ある。

| テーブル | 未保存件数 | 原因フィールド |
|---------|-----------|--------------|
| `retirements` | 8件 | `retirement_date` が NOT NULL だが LLM が null を返す |
| `corrections` | 3件 | `original_announcement_date` が NOT NULL だが LLM が null を返す |

### 対応

1. ✅ `retirement.md` / `correction.md` プロンプトに必須フィールドの明示指示を追加
2. ✅ `main.py` の `REQUIRED_FIELDS` に `retirement_date` / `original_announcement_date` を追加（null 時にネイティブPDFフォールバックが発動する）
3. `logs/reset_issue_d.sql` を SQLite で実行して11件を `failed` にリセット → パイプライン再実行で再保存（**未実行**）

---

## Issue E: モデル/DBスキーマ不一致

### 概要

SQLAlchemy モデルの定義と実際のSQLite DBスキーマが一致していない箇所がある。
`init_db()` が `CREATE TABLE IF NOT EXISTS` を使用しているため、モデルを修正してもテーブルは再作成されない。

### 不一致一覧

| モデルファイル | フィールド | モデルの定義 | 実際のDBの型/PK |
|--------------|-----------|------------|----------------|
| `announcement.py` | `resolution_date` | `primary_key=True` になっている | DBのPKは `(code, disclosure_date)` のみ |
| `completion.py` | `resolution_date` | `primary_key=True` になっている | DBのPKは `(code, disclosure_date)` のみ |
| `completion.py` | `buyback_method` | `Column(String)` | DBは `BIGINT`（型不整合） |
| `completion.py` | `shares_acquired` | `Column(BigInteger)` | DBは `FLOAT`（型不整合） |

### 影響

- `resolution_date` が PK に含まれているため、同一 `(code, disclosure_date)` でも `resolution_date` が異なれば別レコードとして insert されてしまう可能性がある（ただし実際のDBには制約がないため透過的に動作している）
- `buyback_method` 型不整合は文字列を格納しようとした際にエラーになる可能性がある

### 対応（完了）

1. ✅ `announcement.py` / `completion.py` の `resolution_date` から `primary_key=True` を削除
2. ✅ `completion.py` の `shares_acquired` を `Column(Float)` に修正（`buyback_method` は既に `Column(String)` で正しい）
3. 既存DBへの影響なし（`init_db()` は `CREATE TABLE IF NOT EXISTS` のため再作成されない）

---

## 未解決タスク一覧

| # | 内容 | 優先度 | 関連Issue | 状態 |
|---|------|--------|-----------|------|
| 1 | `ir_type.md` 修正: ToSTNeT-3 実績文書を `buyback_completion` に分類するよう追記 | 高 | Issue A | ✅ 完了 |
| 2 | `logs/migrate_tostnet_to_completion.sql` を SQLite に実行して 247件を削除 | 高 | Issue A | ✅ 完了 |
| 3 | migration SQL 実行後、パイプラインを再実行して `failed` 件数の解消を確認 | 高 | Issue A | 未実行 |
| 4 | `retirement.md` プロンプト改善 + `REQUIRED_FIELDS` 追加（retirement_date） | 中 | Issue D | ✅ 完了 |
| 5 | `correction.md` プロンプト改善 + `REQUIRED_FIELDS` 追加（original_announcement_date） | 中 | Issue D | ✅ 完了 |
| 5a | `logs/reset_issue_d.sql` を SQLite で実行して11件をリセット → パイプライン再実行 | 中 | Issue D | ✅ 完了 |
| 6 | モデルの PK 修正（`resolution_date` を PK から除外） | 中 | Issue E | ✅ 完了 |
| 7 | `completion.py` の型不整合修正（shares_acquired を Float に） | 中 | Issue E | ✅ 完了 |
| 8 | 複合文書 335件の値正確性バリデーション（ToSTNeT-3実績値が混入していないか） | 低 | Issue A | 未着手 |
| 9 | 5038・3626 等の「補足説明資料」「取得事項の一部変更」の扱いを決定 | 低 | Issue A | 未着手 |
