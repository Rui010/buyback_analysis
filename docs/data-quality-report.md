# buyback_analysis データ品質レポート

調査日: 2026-06-11  
対象DB: PostgreSQL（SQLiteからコピー済みのもの）

---

## 0. タイトルの使われ方とプロンプト整合性

### 0-1. TDnet タイトルはどこで使われているか

パイプラインは以下の流れでタイトルを使う:

```
tdnet.title
  ↓ (1) get_tdnet_buyback_data: pandas で "自己株" 含むものだけに絞り込み
  ↓ (2) detect_type_by_llm(title, content) → ir_type.md に {title} として渡す
  ↓ (3) parse_text_by_llm / parse_pdf_by_llm(title, ...) → 各 *.md に {title} として渡す
```

タイトルは**型判定（ir_type.md）と構造化抽出（各プロンプト）の両方で LLM に渡されている**。ただし以下の問題がある。

---

### 0-2. 問題 I｜`disclosure_date` を LLM が抽出しているが main.py で上書きされる（二重抽出）

全プロンプト（announcement.md / progress.md / completion.md / correction.md / retirement.md）が `disclosure_date` を抽出するよう指示しているが、main.py の以下のコードでそれを強制上書きしている:

```python
# main.py:170
obj["data"]["disclosure_date"] = row["date"].strftime("%Y-%m-%d")
```

TDnet の `date` 列が正とするなら LLM への `disclosure_date` 抽出指示は不要（ただし LLM が混乱する余地も生む）。同様に `code` も `row["code"]` で上書きすれば LLM 抽出の精度に依存しなくて済む。

---

### 0-3. メモ｜`buyback.md` はデッドファイル（動作への影響なし）

`buyback_analysis/prompts/buyback.md` は現在のパイプラインから参照されていない（`template_map` にも `native_template_map` にも含まれていない）ため、**動作には一切影響しない**。

旧設計の痕跡（`tender_offer_*` フィールドや `type = "announcement"` 等のプレフィックスなし表記）が残っているが、参照されない以上は単なるデッドコード。整理したければ削除してよい。

---

### 0-4. 問題 K｜`data_exists_in_ir_tables` が `retirements` テーブルを確認しない

`data_exists.py` は Announcement / Progress / Completion / Correction の4テーブルのみチェックし、**Retirement を見ていない**。

結果として retirement の URL は重複チェックをパスし、毎回 LLM 呼び出し → `IntegrityError` で握りつぶし（save側の主キー制約でたまたま防いでいる）というフローになっている。LLM 呼び出しが無駄になる。

---

### 0-5. 問題 L｜native プロンプトに `{content}` プレースホルダーがない（設計通りだが要注意）

`announcement_native.md` 等の native 版は `{content}` を受け取らず PDF を直接 Gemini Files API に渡す設計。これは `parse_pdf_by_llm` の引数シグネチャ `(title, pdf_path, code, name, ...)` と整合している。

ただし `completion_native.md` の「探索ガイド」（「ご参考」キーワードを検索してください）は、テキスト抽出版の `completion.md` にも同じ記述があり、両方で一致している ✓。

---

### 0-6. 問題 M｜複合内容のタイトルが1種類にしか分類されない

TDnet には以下のような複数の内容を含む1文書が存在する:

- 「自己株式の取得に係る事項の決定及び自己株式の消却に関するお知らせ」  
  → 発表（announcement）＋消却（retirement）の両方の情報を含む

- 「自己株式の取得状況および取得終了に関するお知らせ」  
  → 進捗（progress）＋完了（completion）の両方を含む

現在のパイプラインは1文書に1つの `DetectType` しか割り当てられないため、もう片方の情報は捨てられる。

---

### 0-7. `ir_type.md` と `get_tdnet_buyback_data` の取得範囲

`get_tdnet_buyback_data` は `title LIKE '%自己株%'` で絞っているが、`equity_compensation`（株式報酬）や `strategic_transaction`（第三者割当など）も「自己株式」を含むタイトルで来るため取得対象に入る。

ただし LLM による型判定は `is_checked` にキャッシュされるため、**同一 URL への LLM 呼び出しは初回のみ**。2回目以降は DB から取得してスキップする。`is_checked` の `equity_compensation` 3,270 件は過去に一度ずつ判定してキャッシュした結果であり、毎回呼ばれているわけではない。動作上の問題はない。

---

## 1. テーブル別レコード数

| テーブル | 件数 |
|---|---|
| buyback_announcements | 1,878 |
| buyback_progress | 3,583 |
| buyback_completion | 2,317 |
| buyback_corrections | 107 |
| buyback_retirements | 102 |
| buyback_is_checked | 12,123 |

---

## 2. 問題一覧（重要度順）

### 問題 A｜completion テーブルに「全フィールドNULL」のゴミレコードが多数

**件数**: 167件（全体の7.2%）  
**ステータス**: ✅ SQLite の `completion` テーブルから対象レコードを DELETE 済み（2026-06-11）

`buyback_completion` に `resolution_date`, `start_date`, `end_date`, `shares_acquired`, `amount_spent_yen` がすべて NULL のレコードが167件存在していた。

**実施した SQL**:
```sql
DELETE FROM completion
WHERE resolution_date IS NULL
  AND start_date     IS NULL
  AND end_date       IS NULL
  AND shares_acquired   IS NULL
  AND amount_spent_yen  IS NULL;
```

**推定原因**: `completion.md` プロンプトには「公開買付（TOB）が含まれている場合はすべての項目を null にしてください」という指示がある。TOBや特殊なフォーマットの完了報告を LLM が null で返してもパイプラインが弾かずそのままDBに保存していた。

**追加対応**: `post_data.py` の `required_fields` に `BUYBACK_COMPLETION` の `shares_acquired` と `amount_spent_yen` を追加し、パイプライン側でも保存前に弾くよう修正済み（2026-06-11）。  
**残課題**: `resolution_date` が主キー列なのに NULL を許容している点はスキーマ設計の見直しが必要。

サンプル（削除済み）:
| code | company_name | disclosure_date |
|---|---|---|
| 7575 | 日本ライフライン | 2025-05-07 |
| 9436 | 沖縄セルラー電話 | 2025-05-08 |
| 4290 | プレステージ・インターナショナル | 2025-05-09 |

---

### 問題 B｜completion テーブルの start_date / resolution_date NULL が多い

| フィールド | NULL件数 | 割合 |
|---|---|---|
| start_date | 542 | 23.4% |
| end_date | 413 | 17.8% |
| resolution_date | 250 | 10.8% |
| shares_acquired | 217 | 9.4% |
| amount_spent_yen | 232 | 10.0% |

**推定原因**: 完了報告書の「ご参考」セクション以降の表形式から LLM が日付・期間を正しく読み取れていない。特に複数の決議が1つの完了報告にまとまっているケースで失敗しやすい。また、`shares_acquired = 0` かつ `amount_spent_yen = 0` のレコードが15件あり、これもパース失敗（null の代わりに 0 が入った）の可能性が高い。

---

### 問題 C｜announcements テーブルの end_date NULL が 336 件（17.9%）

**件数**: 336件

**実態**: ほぼすべて ToSTNeT-3（自己株式立会外買付取引）による翌朝1日だけの買付。ToSTNeT-3 は「翌営業日の始値で1日だけ買う」仕組みのため、PDF上に終了日が明記されていない（または開始日と同日）ことが多い。LLM が抽出できずに null になっている。

**対応方針**: ToSTNeT-3 の場合は `end_date = start_date` とするロジックをプロンプトに追加するか、後処理で補完する。

---

### 問題 D｜buyback_method の表記ゆれ（50種類以上）

`buyback_announcements.buyback_method` に同一概念の表現が大量に存在する。

主要カテゴリとその亜種例（件数は announcements の end_date NULL 内の分布も含む）:

| 正規化後の区分 | 代表的な表記バリエーション（抜粋） |
|---|---|
| 市場買付 | 「東京証券取引所における市場買付」(496)、「東京証券取引所における市場買付け」(202)、「市場買付」(27)、「市場買付け」(24)、「株式会社東京証券取引所における市場買付け」(36) … |
| ToSTNeT-3 | 「自己株式立会外買付取引（ToSTNeT-3）」(243)、「自己株式立会外買付取引（ＴｏＳＴＮｅＴ－３）」(33)、「自己株式立会外買付取引(ToSTNeT-3)」(27)、「自己株式立会外買付取引（ToSTNeT-３）」(25) … 計40種類超 |
| 公開買付 | 「公開買付け」(35)、「自己株式の公開買付け」(14) |
| 取引一任 | 「東京証券取引所における取引一任契約に基づく市場買付」(42)、「自己株式取得に係る取引一任契約に基づく市場買付」(17) … |

また `buyback_method = 'null'`（文字列）が 4件存在する（後述の問題 F）。

**影響**: 買付方法別の集計・フィルタリングが困難。

---

### 問題 E｜is_checked 登録済みだがデータテーブルに保存されていないレコード（パース失敗）

`is_checked` に登録されているが、対応するデータテーブルにレコードが存在しない = パース or 保存失敗と推定される件数:

| detected_type | 未保存件数 |
|---|---|
| buyback_announcement | 123件 |
| buyback_completion | 107件 |
| buyback_progress | 33件 |
| retirement | 15件 |
| correction | 3件 |
| **合計** | **281件** |

これらは再実行しても `is_checked` に登録済みのためスキップされ続ける（現在の `detect_type_by_llm` → `post_url` の流れでは型判定済みならLLM再判定しないが、パース結果が保存されていなくてもスキップされる）。

---

### 問題 F｜`"null"` 文字列がそのまま保存されているフィールド

**ステータス**: ✅ 実施済み（2026-06-11）

LLM が Python `None` ではなく文字列 `"null"` を返した場合、`_sanitize_null_strings()` で変換されるはずだが、一部フィールドに文字列 `"null"` が残っていた。

| フィールド | 件数 |
|---|---|
| completion.start_date | 5 |
| completion.end_date | 5 |
| completion.code | 5 |
| announcements.buyback_method | 4 |
| announcements.start_date | 1 |
| announcements.end_date | 1 |

`completion.code = 'null'` の5件は主キーの一部のため、検索時に `WHERE code = '...' ` で引っかからず実質的な孤立レコードになっていた。

**実施した SQL**:
```sql
-- 1. code='null' の孤立レコードを削除（start_date/end_date も一緒に消える）
DELETE FROM completion WHERE code = 'null';

-- 2. completion の残り "null" 文字列を NULL に変換
UPDATE completion SET start_date = NULL WHERE start_date = 'null';
UPDATE completion SET end_date = NULL WHERE end_date = 'null';

-- 3. announcements の "null" 文字列を NULL に変換
UPDATE announcements SET buyback_method = NULL WHERE buyback_method = 'null';
UPDATE announcements SET start_date = NULL WHERE start_date = 'null';
UPDATE announcements SET end_date = NULL WHERE end_date = 'null';
```

---

### 問題 G｜progress テーブルの cumulative = 0 が 247 件

取得株数・金額が両方 0 の進捗報告が247件（6.9%）存在する。

**2つのケースが混在していると推定**:
1. **正常**: 当該期間中に実際に1株も取得しなかったことを報告している（制度上 0 取得の報告も義務あり）
2. **パース失敗**: null の代わりに 0 が入った

**対応方針（選択肢A + C）**:
- **A（プロンプト修正）✅**: `progress.md` / `progress_native.md` に「数値が見つからない場合は `0` ではなく `null` を返す」指示を追加済み（2026-06-11）。以降の新規レコードはパース失敗なら `null` になり区別可能。
- **C（分析側で除外）**: 既存247件は区別不能なため、集計・分析時は `WHERE cumulative_shares_acquired IS NOT NULL AND cumulative_shares_acquired > 0` で除外する運用とする。

---

### 問題 H｜corrections テーブルの `corrections` JSON がUnicodeエスケープ

`corrections` カラムのJSONが `\uXXXX` 形式でエスケープされた日本語になっている。SQLで直接読むときに可読性が低く、一部の `section` フィールドが「不明」になっているものも多い。機能上は問題ないが、可読性・デバッグのしやすさに影響する。

---

## 3. 数値の正確性（異常値なし）

以下は問題なし:
- 負の金額・株数: 0件（全テーブル）
- 日付フォーマット（YYYY-MM-DD以外）: 0件
- 極端な大きすぎる金額（5兆円超の progress）: 0件
- buyback_amount_yen の最小値（530,145円 = GMSグループ、端数処理による少額取得）: 小規模企業の端数買取として正常範囲

---

---

## 3-2. パース失敗の再処理・通知に関する問題

### 問題 N｜パース失敗した URL が `is_checked` に登録されたまま再処理されない

現在のフロー:
1. `is_checked` に URL が登録されていれば型判定をスキップ
2. 型判定は登録済みでも、データテーブルに保存されていない場合は「パース失敗」
3. しかし `is_checked` への登録は消えないため、次回以降もパースを試みずスキップされ続ける

結果として `is_checked` 登録済みだがデータ未保存の件数が累積している（PostgreSQL調査時点: 281件、SQLite実測: 448件。差分はPG移行後の追加失敗分）。

### 問題 O｜パース失敗が Slack に通知されない

ループ内の個別失敗（PDF 取得失敗・型判定失敗・パース失敗・保存失敗）はすべて `logger.error` でログファイルに書くだけで **Slack には何も通知されない**。

パース失敗件数は `notify_success` のサマリー文字列（`パース失敗:N件`）に含まれるが、これはパイプラインが正常完了した場合のみ通知される。どの URL が失敗したかはログファイルを確認しないと分からない。

**対応方針**:
- 問題 N: `is_checked` に `parse_status`（`saved` / `failed`）カラムを追加し、失敗 URL を次回起動時に再試行できるようにする
- 問題 O: パース失敗時に `notify_error` または警告レベルの Slack 通知を送る（件数まとめでもよい）

---

---

## 3-3. コードレビューで見つかったバグ・不整合

### バグ P｜`is_checked` に URL のユニーク制約がなく、`post_url` の重複防止が機能していない

`IsChecked` モデルの主キーは autoincrement の `id` のみで、`url` にユニーク制約がない。

```python
# models/is_checked.py
id = Column(Integer, primary_key=True, autoincrement=True)  # ← これだけ
url = Column(String)  # ← UniqueConstraint なし
```

`post_url.py` は「主キーエラーが出たらスキップ」するつもりで `IntegrityError` をキャッチしているが、autoincrement id に対する INSERT は絶対に IntegrityError を起こさないため、この catch は**デッドコード**になっている。

結果として同一 URL が複数回 INSERT されているケースが実際に存在する（5 URL、2〜5件ずつ重複）。重複が起きる経路は `DAYS_BACK` ウィンドウのオーバーラップ等と推定。

動作への影響は限定的（`get_detect_type_in_db` が `.first()` を使うため型判定は正常）だが、放置すると重複が増え続ける。また ORM モデルに `url` のインデックスも定義されていないため、SQLite・PostgreSQL 両方で 12,000件超のテーブルに対する URL 検索が毎回フルスキャンになっている。

**修正方針**: `IsChecked` モデルに `UniqueConstraint('url')` と `Index` を追加し、`post_url` の `except IntegrityError` を URL 重複を正しく防ぐコードに直す。

---

### バグ Q｜`main.py` モジュールレベルの `session` がリソースリーク

```python
# main.py line 35（モジュールレベル）
session = SessionLocal()   # ← 使われない・closeされない

def main():
    session = SessionLocal()  # ← こちらが実際に使われ、finally で close される
```

モジュールレベルの `session` は `main()` 内の同名ローカル変数に隠蔽されて一切使われないまま、DB コネクションを保持し続ける。

---

### バグ R｜`post_url.py` の `except Exception` がエラーを完全に飲み込む

```python
except Exception as e:
    session.rollback()
    # ← logger.error も raise もない
```

URL 保存失敗時にログも通知も出ないため、`is_checked` への登録が静かに失敗する。次回実行時に同じ URL が `is_checked` に見つからず、LLM 型判定が再実行される。

---

### 不整合 S｜`sqlite_engine.py` のエラーメッセージと環境変数名が違う

```python
# sqlite_engine.py
DATABASE_URL = os.getenv("SQLITE_DB_URL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL が設定されていません")  # ← 変数名が違う
```

エラーが出たときに `DATABASE_URL` を設定しようとして混乱する。

---

### 不整合 T｜`CLAUDE.md` のモデル名とコードが一致しない

```python
# consts/llm_model.py
LLM_MODEL_GEMINI = "gemini-2.5-flash-lite"
```

`CLAUDE.md` には `gemini-2.0-flash-lite` と記載されている。コードが正しいとすれば CLAUDE.md が古い。

---

### 不整合 U｜`post_url.py` の docstring が古い

```python
def post_url(session: Session, code: str, url: str, detected_type: str) -> None:
    """
    Args:
        data (dict): 保存するデータ（辞書形式）  # ← 引数名・型が現在の実装と違う
    """
```

---

## 4. 修正ロードマップ

依存関係を考慮した推奨実施順序。

### フェーズ 1 — 小さいコード修正（まとめて1コミット）

| 問題 | 内容 |
|---|---|
| バグ Q | `main.py` モジュールレベルの未使用 `session` を削除 ✅ |
| バグ R | `post_url.py` の `except Exception` に `logger.error` を追加 ✅ |
| 不整合 S | `sqlite_engine.py` のエラーメッセージを `SQLITE_DB_URL` に修正 ✅ |
| 不整合 U | `post_url.py` の古い docstring を修正 ✅ |

### フェーズ 2 — `is_checked` モデル変更（P と N はセット）

バグ P（UniqueConstraint/Index 追加）と問題 N（`parse_status` カラム追加）は同じモデル・同じマイグレーションで対応する。バグ P を先に直さないと、`parse_status` の再試行ロジックが URL 重複で正しく動かない。

| 問題 | 内容 |
|---|---|
| バグ P | `IsChecked` モデルに `UniqueConstraint('url')` と `Index` を追加、`post_url` の重複防止ロジックを修正 ✅ |
| 問題 N | `is_checked` に `parse_status`（`saved` / `failed` / `pending` / `skipped`）カラムを追加し、`failed` の URL を次回起動時に再パースする ✅ |

### フェーズ 3 — パイプラインの保存・通知ロジック修正

| 問題 | 内容 |
|---|---|
| 問題 O | パース失敗時の Slack 通知追加（フェーズ 2 で `parse_status` が入ってから判定しやすくなる） ✅ |
| 問題 A | `completion` 全 NULL レコードを保存前に弾く ✅ |
| 問題 K | `data_exists_in_ir_tables` に `retirements` テーブルのチェックを追加 ✅ |

### フェーズ 4 — プロンプト改善（データ精度向上）

| 問題 | 内容 |
|---|---|
| 問題 C | ToSTNeT-3 の `end_date` を `start_date` と同値にする指示をプロンプトに追加または post 処理で補完 ✅ |
| 問題 B | `completion` の start_date/end_date NULL が多い → プロンプトで複数決議の扱いを明確化 ✅ |

### フェーズ 5 — データクレンジング（既存データの後処理）

| 問題 | 内容 |
|---|---|
| 問題 F | `"null"` 文字列を NULL に UPDATE するクレンジングスクリプトを実行 ✅ |
| 問題 D | `buyback_method` を 6 カテゴリ（市場買付 / ToSTNeT-3 / 公開買付 / 取引一任 / 信託方式 / その他）に正規化するビューを追加 → **現時点では不要のためスキップ**。将来、買付方法別バックテスト（取得完了率・宣言後の株価リアクション比較）を行う際に実装する。 |

### 後回しでよいもの

| 問題 | 内容 |
|---|---|
| 不整合 T | CLAUDE.md のモデル名を `gemini-2.5-flash-lite` に更新 ✅ |
| 問題 G | progress の 0 値レコードを正常/失敗で区別 → プロンプト修正（A）＋分析時除外（C）で対応 ✅ |

---

## 5. まとめ

**データ品質として影響が大きい問題:**
1. **completion の全 NULL 保存（167 件）** → 完了テーブルをそのまま分析に使うと 7% がゴミ
2. **281 件のパース失敗が再処理されない** → is_checked でスキップされ続けている
3. **buyback_method の表記ゆれ（50 種類超）** → 方法別集計・フィルタリングができない

**コードの信頼性として問題:**
4. **`is_checked` の URL 重複防止が機能していない**（バグ P）→ 重複が蓄積し続ける
5. **`post_url` のエラーが無音で飲み込まれる**（バグ R）→ 登録失敗が気づかれない
6. **モジュールレベルの未クローズセッション**（バグ Q）→ DB コネクションリーク
