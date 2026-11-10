# 中計目標の抽出範囲と属性の改訂 実装報告

作成日: 2026-11-10  
報告元: `C:\apps\buyback_analysis`  
宛先: `C:\apps\ir-analytics-platform`  
対象仕様: `docs/plans/handoffs/buyback-midterm-target-extraction.md`（2026-11-10改訂版）

## 0. 要約

- 第4節の出力契約（`metrics`の属性、`reference_values`）を、text・native両方のプロンプトと保存処理に実装した
- 15文書は第8節の手順1（本番DBに書き込まないローカル実行）で抽出し、**手順2の本番RERUNは行っていない**。LLMの再実行費用を避けるため、ローカル実行の結果をそのまま本番SQLiteへ採用した（実装先の判断）。旧結果は版として残っている
- このため、**15文書の採用版にはrun記録（run ID）がない**（`origin=unrecorded`）。プロンプトhashは本書に記載する
- 受入を止める条件4・7は全件満たした。条件3は10件中8件、条件5は34件中20件

## 1. 変更したプロンプト・コード・テスト（§9-1）

### プロンプト

| ファイル | SHA-256 |
|---|---|
| `buyback_analysis/prompts/midterm_plan_native.md`（本番・今回の抽出で使用） | `633d49dd83c93312686948370768e8d04cd4ecf1210e8b51ea7eff61ab16c089` |
| `buyback_analysis/prompts/midterm_plan.md`（text方式） | `8fe93fd80212e49cb20d7a97e79d8a29167867210ae91d0e7a78c91e1336fdc6` |

本番は`MIDTERM_USE_NATIVE_PDF=true`（native方式）で動いている。

### コード

| ファイル | 内容 |
|---|---|
| `midterm_plan_analysis/usecase/normalize_midterm_metrics.py`（新規） | LLM出力の正規化（第7節）。下記「第7節の扱い」 |
| `midterm_plan_analysis/usecase/run_midterm_stages.py` | metrics抽出の結果を正規化して返す。`extractor_version`を`parse_pdf_by_llm:1+midterm_metrics_normalizer:1`（textは`parse_text_by_llm:1+…`）にする |
| `buyback_analysis/usecase/get_pdf_data.py`、`tdnet_provenance/usecase/prepare_pdf_input.py` | text方式のページの目印（4.4）。中計のmetricsだけに`--- page N ---`入りの本文を送る。keywords・classification、他パイプラインの入力は変えていない |
| `midterm_plan_analysis/models/midterm_plan.py`、`usecase/post_midterm_plan.py` | `reference_values`列（JSON文字列）の追加と保存 |
| `midterm_plan_analysis/usecase/migrate_reference_values.py`、`scripts/migrate_midterm_reference_values.py`（新規） | 既存SQLiteへの列追加（オンラインバックアップを作成してから追加） |
| `midterm_plan_analysis/usecase/determine_midterm_status.py`（新規）、`main.py` | `extraction_status`の判定を関数に切り出した（判定規則は従来どおり） |
| `midterm_plan_analysis/usecase/compare_midterm_fixture.py`、`scripts/verify_midterm_targets.py`（新規） | 正解データとの突き合わせと、本番DBに書き込まないローカル実行 |
| `midterm_plan_analysis/usecase/import_verified_result.py`、`scripts/import_midterm_verified_results.py`（新規） | ローカル実行の結果を、既存の採用切替（`adopt_result`）経由で本番SQLiteへ採用する |

### テスト

`tests/`に追加・更新（正規化76件、突き合わせ32件、ページの目印、列・保存・migration、採用など）。全693件が成功。

### 第7節の扱い（実装先が決める事項）

- 新しい項目が欠けたresponseは**失敗扱いにせず補って保存する**。`target_scope`は`unknown`、`revision_role`は`current`、`consolidation_label`・`bound`・`value_upper`・`value_text`・`page`は`null`、`reference_values`がなければ`[]`、`kind`は`unknown`
- `value`の文字列は、全角数字・桁区切り・`△`/`▲`の負号・「7.0以上」「約100」「5〜7」を数値に直し、元の表記を`value_text`に残す。`bound`が欠けていれば表記から導く。直せなければ`value=null`
- 計画の終了期間（`plan_end_year`・`plan_end_period_label`・`plan_end_fiscal_end`）がすべて`null`の文書では、`plan_final`・`plan_interim`・`long_term`を`unknown`にする（4.5）。`cumulative`は残す
- `reference_values`には`bound`・`value_upper`を持たせない（4.2の項目にないため）
- 空の`segment`は項目ごと削除する
- 同じ値が`metrics`と`reference_values`の両方にあれば`[WARNING]`ログを出し、保存はする

## 2. 15文書の採用結果、LLM呼び出しと費用（§9-2）

- run ID: **なし**。ローカル実行はprocessing_runを記録しない経路で行い、結果を`adopt_result`で採用したため、新しい版は`origin=unrecorded`・`run_ids=[]`
- 採用の切替: 2026-11-10 19:47（JST）に15文書すべてで成功。各文書の旧結果は`origin=legacy`の版として残っており、旧版へ戻せる
- バックアップ: 書き込み前にSQLiteのオンラインバックアップを作成した
- `midterm_plans`に`reference_values`列を追加した。PostgreSQLの`buyback_midterm_plans`にも同じ列を追加済みで、次回の同期から反映される

| コード | 公表日 | extraction_status | 旧版（legacy） | 採用版（unrecorded） | LLM呼び出し | 入力token | 出力token |
|---|---|---|---|---|---:|---:|---:|
| 1762 | 2025-05-14 | ok | 10c0fc4e-a97e-4aa3-adb3-524d3896118e | 7b3b61a0-11ba-4541-858c-e7a8323e507f | 1 | 19,819 | 2,636 |
| 1814 | 2026-04-24 | ok | 1c19532b-637d-40d4-85ea-6bcbef230991 | f255c2bd-1ada-4b6e-a780-bf732e06930d | 1 | 16,587 | 2,168 |
| 1941 | 2025-04-28 | ok | a9fff0ee-3e1b-416a-b7c9-759fde9c5213 | d39158d8-c427-4d1c-8eee-c1647ca539cc | 1 | 7,971 | 1,865 |
| 1941 | 2026-04-28 | ok | bc543741-7857-4229-9691-de9c55fd66d7 | 128a6247-058d-426a-9197-7cdf73664892 | 1 | 3,656 | 2,494 |
| 3529 | 2025-09-24 | ok | ae11cd98-ba98-4e44-a74d-81ddcc379d95 | 1ee0dd1a-ce81-47d2-840d-fccdb51d1297 | 1 | 16,394 | 2,737 |
| 3529 | 2026-05-13 | withdrawn | b327a615-3324-4562-b5b2-2a3555be4372 | 0bd759a7-0bbf-45ad-bc62-94a1eaabbba1 | 1 | 4,170 | 166 |
| 5994 | 2025-09-25 | postponed | 3223f072-a141-4f86-a695-37bc5ba0ae14 | bd95c078-e179-462f-b9eb-025bc897376f | 2 | 4,040 | 164 |
| 5994 | 2026-05-14 | ok | ca511b67-fea8-4043-b483-11993880461d | fe5ea6e3-94af-46ff-b3ec-5098827cd5f9 | 1 | 22,600 | 1,727 |
| 5994 | 2026-05-15 | ok | 3439a9df-9c51-42a8-ade0-493fd37e15a3 | 4832195f-6a47-4ea5-b3a0-650a98b3ec3a | 1 | 22,611 | 1,753 |
| 5994 | 2026-05-20 | ok | 179a4a38-7e1f-4cd2-9208-c45270da47af | 777b7f28-73aa-4225-ad76-0afa496c4705 | 1 | 32,634 | 1,770 |
| 4042 | 2025-05-23（概要） | ok | 086f3ab0-afcf-487a-8a3d-7d38f3bfd364 | a2f5d545-ffec-4937-87e8-00f54e11a4f8 | 1 | 5,230 | 2,734 |
| 4042 | 2025-05-23（説明資料） | ok | 8a6427c6-1482-4c43-b1cb-6cadd9dae360 | e1395eb7-6a52-4a65-9e9d-942eb79510b2 | 1 | 32,089 | 1,233 |
| 2811 | 2026-02-02 | ok | b5134c74-3524-445f-ad12-70c0cb3c02ea | 097e756e-fe57-486e-83fb-c294e89d6986 | 1 | 27,353 | 1,928 |
| 2874 | 2025-11-13 | ok | f394937a-0697-4582-8bc1-e93519023df1 | 699d6da6-e8b7-4f7a-a092-d4a43f54a4fa | 1 | 3,626 | 2,281 |
| 8185 | 2025-04-18 | ok | b4f130e4-6e20-4c6b-a9c4-bebb55fb0204 | c5b32402-5053-4238-84b0-113e29302611 | 1 | 4,156 | 2,013 |

採用版の抽出（2回目）の合計は、LLM呼び出し16回（metrics 15回、classification 1回）、入力222,936 token、出力27,669 token。プロンプトを補強する前の1回目も含めると、実LLMの呼び出しは計31回。モデルは`gemini-3.1-flash-lite`。

費用は、2026-07時点の単価（入力$0.25・出力$1.50 / 100万token、未再確認）で1回約$0.10、2回で約$0.20と見積もる。本番に単価の環境変数（`LLM_PRICE_*`）を設定していないため、記録上の費用はない。

### 抽出条件

- native方式。PDFは本番の保存先からコピーし、15件とも正解データのSHA-256と一致することを確認した（TDnetの配信元では15件とも取得できなくなっていた）
- `temperature`は指定していない（自己株買い等と共通の設定）。同じ入力でも回ごとに結果がぶれる（第4節の条件3を参照）

## 3. 抽出結果JSON（§9-3）

`docs/handoffs/midterm_target_extraction/results_20261110.json`（15文書の`data`。`metrics`・`reference_values`・計画期間を含む）。本番の`midterm_plans`の採用版と同じ内容である。

## 4. 第8節の条件ごとの結果（§9-4）

突き合わせは`scripts/verify_midterm_targets.py`（判定は`compare_midterm_fixture.py`）で行った。正解データと同じく全社の売上高・営業利益・事業利益を、円に換算した値で照合した。抽出結果の期末（`target_fiscal_end`・`period_fiscal_end`）が`null`のときは、期間表記の年が矛盾しないものを一致とした（条件1の「判断できる場合」）。

| # | 条件 | 結果 |
|---|---|---:|
| 1 | 全社目標がすべて`metrics`にあり、値・単位・期末が一致 | 43/43 |
| 2 | 計画期間外の目標が`target_scope=long_term` | 7/7 |
| 3 | 見直し前の目標が`revision_role=previous` | 8/10 |
| 4 | 業績予想・実績・見込が`metrics`に入っていない | 0件（34/34） |
| 5 | 目標表に並ぶ値が`reference_values`にあり、`kind`が一致 | 20/34（実績16/22・見込2/2・予想2/10） |
| 6 | 8185の連結・単体が`consolidation_label`で区別 | 8/8 |
| 7 | 1814・4042の全社目標に`segment`なし | 9/9 |
| 8 | 撤回・延期の`extraction_status`が従来どおり | 2/2 |

### 満たさない値

| 条件 | 文書 | 値 | 理由 |
|---|---|---|---|
| 3 | 1814 2026-04-24 | 売上高 2031/03 1,000億円以上（見直し前） | p.3の見直し前の目標を抽出していない（p.5の見直し後だけを抽出） |
| 3 | 1814 2026-04-24 | 営業利益 2031/03 50億円以上（見直し前） | 同上 |
| 5 | 1762 2025-05-14 | 売上高 3,466・営業利益 114（2025/03 実績） | p.11の表の実績を抽出していない。目標はp.2の表から抽出しており、p.2の表には実績がない |
| 5 | 1941 2025-04-28 | 売上高 2,300・営業利益 220（2026/03 予想） | p.8のグラフの「（予想）」を抽出していない |
| 5 | 3529 2025-09-24 | 売上高 218・営業利益 -9（2025/03 実績） | p.11の表の実績を抽出していない |
| 5 | 5994 2026-05-14 | 売上高 44,500・営業利益 1,200（2027/03 予想値） | p.13の予想値を抽出していない（p.1の実績は抽出済み） |
| 5 | 4042 2025-05-23（説明資料） | 売上高 10,500・営業利益 1,080（2026/03 予想） | p.51のセグメント表の合計行の予想を抽出していない |
| 5 | 2811 2026-02-02 | 売上収益 3,100・事業利益 230（2026/12 予想） | p.17・p.45の予想を抽出していない（p.17の実績は抽出済み） |
| 5 | 8185 2025-04-18 | 営業利益 2,193（連結）・2,821（単体）（2025/02 実績） | 売上高の実績は抽出したが、営業利益の実績を抽出していない |

参考:

- 条件3の1814は、プロンプトを補強する前の1回目では10件とも`previous`として抽出していた。同じ入力でも回ごとに結果がぶれる。8185の長期目標（配当性向・DOE等）も1回目にだけ現れた
- 条件5の取りこぼしは、目標が複数のページ・表に載っている資料で、`metrics`に使ったのと別の表に並ぶ値に集中している。補強後のプロンプトでもすべては拾えていない
- 期末（`target_fiscal_end`）は、多くの文書で`null`である（「2027年度」等の表記で、資料内に決算期との対応がないため。規則どおり）。照合は期間表記の年で行った
- `page`は、2811などで正解データと異なる値がある（同じ値が複数ページに載っているため）

## 5. 1,588文書を再抽出する場合の費用見積もり（§9-5）

今回の15文書の平均（1文書あたり入力約14,900 token・出力約1,800 token）と、2026-07時点の単価（未再確認）による概算。

| 範囲 | 見積もり |
|---|---|
| metricsのみ | 約$10（約1,500円） |
| `RERUN_URLS`の既定（`RERUN_ALLOW_REUSE=false`）。本番は`MIDTERM_EXTRACT_KEYWORDS=true`なのでkeywordsも呼び直す | 約$20〜25（約3,000〜4,000円） |

対象の15文書には50ページを超える資料も含まれており、1,588文書の平均とは異なる可能性がある。実行前に単価を再確認すること。

## 6. 報告で区別する項目（§10）

| 項目 | 状態 |
|---|---|
| local commit | 実施（本報告と同じcommit） |
| push | 実施 |
| 本番反映（実行環境のコード更新） | **未実施**。本番の旧コードは新しい列を無視して動く。新しく公表される文書は、反映まで旧プロンプトで抽出される |
| 本番SQLiteへの書き込み | 実施。15文書の採用切替と`reference_values`列の追加 |
| 本番PostgreSQLへの書き込み | `buyback_midterm_plans`への`reference_values`列の追加を実施。データは次回の同期でコピーされる |
| 実LLMの呼び出し | 31回（ローカル実行2回分。本番RERUNはなし） |

## 7. 確認してほしいこと

1. 15文書の採用版にrun記録がない（`origin=unrecorded`）ことを許容するか。許容しない場合は、コードを本番へ反映した後に`RERUN_URLS`で再抽出する（費用は約15円）。ただし、回ごとのぶれで結果が変わる可能性がある
2. 条件3（1814）・条件5の不一致を許容するか
