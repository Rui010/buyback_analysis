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

### 生成済み作業ファイル（`logs/` に退避済み）

| ファイル | 内容 |
|---------|------|
| `logs/insert_skipped.sql` | 214件の上場廃止URLを `is_checked` に `skipped` として INSERT するSQL（**未実行**） |
| `logs/pdf_download_failures.csv` | PDF取得失敗URL一覧（650件）|
| `logs/downloaded_files.txt` | 手動ダウンロードできたPDFのファイル一覧 |
| `logs/skipped_comparison.csv` | UNIQUE制約スキップ102件のログ値 vs PostgreSQL値の比較結果 |

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

`buyback_announcements` / `buyback_completion` / `buyback_progress` テーブルの PRIMARY KEY が `(code, disclosure_date)` であり、**同日2枚配信**を想定していない。

### 対応案（未着手、要検討）

| 案 | 内容 | 工数 | トレードオフ |
|----|------|------|------------|
| **A) URLをPKに加える** | PK を `(code, disclosure_date, url)` に変更 | 大（スキーマ変更・移行） | 2レコードに分かれるが両方保存できる |
| **B) 2枚セットを検知して振り分け** | TDnetクエリ時にタイトルで「決議」と「ToSTNeT-3結果」を判別し、決議→`announcement`、結果→`completion` として保存 | 中 | 判定ロジックが複雑 |
| **C) 処理順を保証** | TDnetクエリのORDER BYを調整し「取締役会決議」を必ず先に処理 → ToSTNeT-3結果は `is_checked` で `skipped` に | 小 | ToSTNeT-3実績データは失われる |

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

### 対応（未着手）

1. `retirement.md` / `correction.md` プロンプトを改善して null を返しにくくする
2. ネイティブPDFフォールバックを `retirement` / `correction` にも適用する
3. `REQUIRED_FIELDS` に `retirement` と `correction` の必須フィールドを追加する

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

### 対応（未着手）

1. モデルから `resolution_date` を primary_key から外す
2. `completion.py` の `buyback_method` → `Column(String)`、`shares_acquired` → `Column(Float)` に修正
3. 修正後、新しいDBに対しては `init_db()` で正しいスキーマが作られる（既存DBは別途 ALTER TABLE が必要）

---

## 未解決タスク一覧

| # | 内容 | 優先度 | 関連Issue |
|---|------|--------|-----------|
| 1 | Issue A の対応方針を決定（A/B/C のいずれか） | 高 | Issue A |
| 2 | `retirement.md` プロンプト改善 + `REQUIRED_FIELDS` 追加（retirement_date） | 中 | Issue D |
| 3 | `correction.md` プロンプト改善 + `REQUIRED_FIELDS` 追加（original_announcement_date） | 中 | Issue D |
| 4 | モデルの PK 修正（`resolution_date` を PK から除外） | 中 | Issue E |
| 5 | `completion.py` の型不整合修正（buyback_method, shares_acquired） | 中 | Issue E |
| 6 | `skipped_comparison.csv` の77件差異を確認し、DBの値が誤っていれば UPDATE SQL を作成 | 低 | Issue A |
| 7 | 5038・3626 等の「補足説明資料」「取得事項の一部変更」の扱いを決定 | 低 | Issue A |
