# 中計の公表日のずれの修正（作業A）作業記録

実施日: 2026-11-11
依頼: `C:\apps\ir-analytics-platform\docs\plans\handoffs\buyback-midterm-date-and-prompt-fixes.md` 第2節

## 原因

16行とも、パイプラインのコードではなく、手で本番SQLiteに投入したSQLが原因。

| 時期 | 作業の跡（開発PCの`data/`、リポジトリ外） | 対象 | 内容 |
|---|---|---|---|
| 2026-06-20 | `insert_midterm_plans.sql` | 3003・2915・8362・6574・7604 | `metrics`が空だった行を`UPDATE`したとき、`disclosure_date`も1日早い値で上書きした |
| 2026-07-20 | `add_data_20260720/`（`missing_midterm_plans_group_a.csv`、`insert_midterm_plans_20260720.sql`、`insert_4825_native.sql`） | 残りの11件 | 対象の一覧（CSV）の`date`列がすでに1日早かった。PDFもその日付のフォルダに保存してサーバーへコピーし、`midterm_plans`・`midterm_plan_keywords`に`INSERT`した |

根拠:

- 2026-05-22のバックアップ（`bk_midterm_plans_20260522`）では、3003・2915・8362は正しい日付で、`metrics`は空`[]`だった
- 7604は、2026-06-12に通常のパイプラインが正しいフォルダ（`20260612`）でPDFを保存して処理していた（`app.log.2026-06-12`）
- `add_data_20260720/`の下のフォルダ名（`20250408`など）が、ずれた日付と一致する
- 2026-09-26以降のバックアップでは、16件ともずれている

1日ずれた理由（推定）: `tdnet.date`（`timestamp without time zone`、JSTの0時）を、UTCで表示するツール（例: postgresのMCPは`2025-04-08T15:00:00.000Z`と表示する）の出力から読み、その日付部分を使った。CSVを作った手順の記録はないので、確定はできない。

## 再発しないことの根拠

- `midterm_plan_analysis/main.py`・`backfill_keywords.py`は、2026-04の実装当初から`row["date"].strftime(...)`（naiveなdatetime）で`disclosure_date`とPDFフォルダを作る。両者は同じ値から作るので、ずれない
- `tdnet`の収集スクリプトは、一覧ページの日付を入れて新しい行をINSERTするだけ
- 手動投入の対象は2026-07-15までの文書だけ（「2026-07-15以降にはない」ことと合う）
- 手で日付を扱うときは、SQL側で`to_char(date,'YYYY-MM-DD')`を使う
- `tdnet.date`から日付文字列を作る処理のテストは、まだない（`main.py`の中の1行で、テストの対象外のため）。作業B・Cのコミットで`usecase/`の関数に切り出し、テストを加える

## 実施内容

1. 本番DBのバックアップ: `\\100.64.1.30\dq-c\sqlite_db\buyback.db.bak-midterm-date-fix-20261111144347`
2. `midterm_plans`の16行と、`midterm_plan_keywords`の135行（11文書分）の`disclosure_date`を`tdnet.date`の日付に更新した。更新前の値が想定した誤りの日付であることを確認してから更新した。修正前後の値: [db_changes.csv](db_changes.csv)
3. PDF: 10件を`tdnet.date`の日付のフォルダにコピーした（`shutil.copy2`、元のファイルは残した）。10件ともSHA-256が元と一致した。150A（515213）・3994は両方のフォルダに元からあり、SHA-256は一致した。残りの4件は正しいフォルダにだけある。結果: [pdf_copies.csv](pdf_copies.csv)
4. 確認: `midterm_plans`の1,721行、`midterm_plan_keywords`の2,261行のどちらでも、`tdnet.date`とのずれは0件
5. 台帳: `tdnet_source_documents`・`result_versions`には、16件とも登録がない（誤った`storage_uri`の登録はない）

## 6183の再抽出（受入条件）

2026-11-11 14:47（JST）に、サーバーで`RERUN_URLS=https://www.release.tdnet.info/inbs/140120250409511440.pdf`を指定して`python -m midterm_plan_analysis.main`を実行した（code commit `ef4c9ae`）。

- 台帳: `tdnet_source_documents`に新しく登録された。`storage_uri=tdnet-pdf://20250409/140120250409511440.pdf`、`published_at=2025-04-09T15:30:00+09:00`、`source_hash=545cea31…a071a`
- run: `metrics`（run `bf6d2581…`、`midterm_plan_native.md`、入力26,282・出力1,433 token）と`keywords`（run `d28377d4…`、入力23,581・出力549 token）の両方が、`input_locator=tdnet-pdf://20250409/...`で`succeeded`
- 採用: 旧結果は`origin=legacy`の版（`d587bc99…`）として残り、新しい`run`の版（`40eafb6f…`）が採用された。`midterm_plans`は`disclosure_date=2025-04-09`、`extraction_status=ok`
- 同じ日の13:26（修正前）のrun `f3b2c4b2…`は`download_failed`のまま履歴に残っている

このときのプロンプトは改訂前のもの。1バッチ目の文書として、作業B・Cの後で抽出し直す。

## 依頼にない追加の修正

- `midterm_plan_keywords.disclosure_date`も同じようにずれていたので、合わせて直した（依頼書は`midterm_plans`だけを挙げていた）
