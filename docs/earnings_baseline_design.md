# 業績予想の起点データ（前期実績・当期初回予想）収集 設計メモ

## 背景・目的

`forecast_revision_analysis` は「予想がどう修正されたか」の推移は持っているが、修正の起点となる**当期の初回予想**と、その前提となる**前期実績**を持っていない。このため、次のような分析ができない。

- 初回予想が保守的で株価が下がり、後の上方修正で株価が上がるケースにおける「前期実績との乖離」の定量化
- データが溜まった後の「当期実績との乖離」（＝初回予想の精度）
- 経年で見た「経営陣の予想開示スタンス」（強気/保守的に出す傾向、下方修正を渋る傾向など）の推定

これらは全て「前期実績」「当期初回予想」を起点データとして持ってはじめて成立する。本メモはこの起点データを収集する新規パイプラインの設計を扱う。

### データの繋がり方

決算短信（本決算のみ）は1文書で2つの決算期に関する値を同時に開示している。

```
[FY N決算短信]                          [FY N+1決算短信]
 当期実績(FY N) ─┐                       当期実績(FY N+1) ─┐
                 │                                        │
 次期予想(FY N+1)─┴─→ 当期初回予想(FY N+1)                  └─→ 当期初回予想(FY N+2)
                        │
                        ├─ forecast_revision_metrics（既存）で修正推移を追跡（fiscal_year=N+1）
                        │
                        └─ FY N+1決算短信の「当期実績(FY N+1)」と比較 → 初回予想の精度
```

つまり1文書から `fiscal_year=N`（当期実績）と `fiscal_year=N+1`（次期初回予想）の2つの決算期分のデータが取れる。これを`code`+`fiscal_year`+`consolidation_type`+`metric_name`で`forecast_revision_metrics`とJOINすれば、初回予想→修正の推移→実績の一本の線になる。

---

## データ取得元・対象スコープ

PostgreSQLの`tdnet`テーブルに対する実データ検証（2025-04〜2026-07、約15.5ヶ月分）を踏まえ、フィルタは以下とする。

- タイトルに **「決算短信」を含み、「四半期」「訂正」「一部」「中間」のいずれも含まない** 行を取得する
  - 「四半期」除外：四半期決算短信は次期通期予想の初回開示に当たらないため対象外（全パターンで「四半期」を含むことを確認済み）
  - 「訂正」「一部」除外：`（訂正・数値データ訂正）「YYYY年３月期 決算短信...」の一部訂正について`のような訂正告知が**884件（全体の9.7%）**該当し、実データを含まない告知（`過年度有価証券報告書等の訂正報告書の提出...`等）も混在するため除外する。訂正の扱いは別機能（後述）で対応する
  - 「中間」除外：J-REIT・ETF・PRO Market銘柄が半期報告を「中間決算短信」というタイトルで出しており、「四半期」を含まないため誤って本決算扱いになる（**335件**該当）。全て除外する
- `Brands`テーブル（PostgreSQL、`code`+`market`）と結合し、`market`が`プライム`/`スタンダード`/`グロース`のいずれかの行のみを対象とする
  - ETF・ETN（125件相当）はそもそも業績予想の概念を持たない
  - PRO Market（186件相当）は開示規制が緩く、決算短信の開示自体が不安定なため対象外とする
  - REIT等は「中間」除外で大部分除外されるが、念のため`market`条件でも二重に絞る
- まずは2026年4月以降を対象に運用を開始する（ユーザー方針②）。過去分のバックフィルは起点データが安定した後の別タスクとする（①は保留）

---

## 訂正告知のSlack通知（別機能）

抽出パイプラインとは別に、除外した「決算短信」＋「訂正」or「一部」に該当する行を検知して日次でSlack通知する軽量機能を設ける。

### 動機

訂正告知はLLM抽出対象からは除外するが、実績・初回予想の数値が事後的に訂正された事実は無視できない（起点データの信頼性に関わる）。抽出はせず、人が見て個別に判断できるよう通知だけ行う。

### 件数感（検証結果）

884件/約15.5ヶ月。決算season（4-5月）に集中し月155〜164件（1日5〜6件相当）、閑散期は月10〜30件（1日1件未満）。既存3パイプラインと同様に**1件ずつ通知せず日次サマリー1本**にまとめれば、ピーク時でも1日1メッセージで収まる。

### 実装方針

- 抽出パイプラインの一部ではなく、`get_tdnet`相当のクエリ結果をそのままSlackに整形して送るだけの軽量チェックとする（LLM呼び出し・DB保存は不要）
- `interface/notifier.py`の`notify_success`と同様の形式で、「本日の決算短信訂正: N件」＋タイトル・URL一覧を送る
- 既存の日次バッチ（`earnings_baseline_analysis/main.py`）の末尾に組み込む方針で実装した（バッチ数を増やさずに済むため）。抽出パイプラインの成功通知（`notify_success("earnings_baseline_analysis", ...)`）とは別に、`notify_earnings_baseline_corrections()`が`notify_success("earnings_baseline_corrections", ...)`という別のSlackメッセージとして送信する（該当0件の日は送信しない）

---

## テーブル設計

`forecast_revision_details`/`_metrics` と同じ「parent（文書単位）+ child（指標行単位）」構成を踏襲する。

```
earnings_baselines            # 文書単位（決算短信1件 = 1行）
├── code                (PK)
├── url                 (PK)
├── disclosure_date
├── fiscal_year_actual        # 当期実績の対象年度（例:「2026年3月期」→2026）
├── fiscal_year_forecast      # 次期初回予想の対象年度（fiscal_year_actual + 1）
├── llm_model
├── extraction_status         # ok / no_data / failed
└── extracted_at

earnings_baseline_metrics     # 指標行単位（1行=1指標×1決算期×1連結区分×1期間区分×1種別）
├── id                  (PK autoincrement)
├── code
├── url                        # earnings_baselines.url に対応（非正規化・追跡用）
├── fiscal_year                # actualはfiscal_year_actual、initial_forecastはfiscal_year_forecastと一致
├── period_type                # '1q'/'2q'/'3q'/'4q'（4q=通期）。forecast_revision_metricsのPeriodTypeと同じ語彙・4値をそのまま流用する
├── consolidation_type         # 'consolidated' / 'non_consolidated'
├── metric_name                # forecast_revision_metricsと同じ正規化ルールを使う（sales/bussiness_income/...）
├── value_type                 # 'actual'（当期実績）/ 'initial_forecast'（次期初回予想）
├── label_raw                  # PDF原文ラベル
├── value                      # 数値（レンジの場合は下限）
├── value_upper                # レンジの上限（レンジでない場合はnull）
└── UniqueConstraint(code, fiscal_year, period_type, consolidation_type, metric_name, value_type)
```

`forecast_revision_metrics`の自然キー設計（v2.2でfiscal_year/consolidation_typeを追加した教訓、[docs/forecast_revision.md](./forecast_revision.md) §7）に合わせ、複合PKではなくサロゲートPK（`id`）+`UniqueConstraint`とする。

`url`を自然キーに含めない理由：同じ`code`+`fiscal_year`の`actual`値は「その決算期の決算短信」1文書からしか出ないため、`url`を鍵に含めなくても一意性は`code`+`fiscal_year`+`period_type`+`consolidation_type`+`metric_name`+`value_type`で担保できる。含めると訂正版（別URL）が来た際に新規行として重複してしまい、むしろ整合性を損なう。

> **`period_type`を追加した理由（サンプルPDF検証で判明）**：当初は`fiscal_year`単位で1指標1行の想定だったが、実データ（ＣＳランバー7808）で「次期業績予想」に**「第２四半期(累計)」と「通期」の2行が同時開示**されているケースを確認した。`period_type`が無いと同一`fiscal_year`の2Q分・4Q分が自然キーで衝突してしまうため、`forecast_revision_metrics`と同じ`period_type`列を追加した。
>
> **値域を`2q`/`4q`の2値から`1q`/`2q`/`3q`/`4q`の4値に拡張した理由**：上記5件のサンプル検証では2q/4qしか観測されなかったが、別途確認したキオクシアホールディングス（285A、2026年3月期決算短信〔IFRS〕）の「３．2027年３月期の連結業績予想」で、通期予想とは別に**第1四半期単体の予想**（売上収益・Non-GAAP営業利益・営業利益・Non-GAAP親会社所有者帰属四半期利益・親会社所有者帰属四半期利益の5指標）が開示されているケースを確認した。業績変動が大きい業種（半導体メモリ等）が四半期単位で予想を細かく出す運用があるため、2値限定は実データを取りこぼす。`period_type`は`forecast_revision_metrics`の`PeriodType`Enum（`1q`/`2q`/`3q`/`4q`）をそのまま流用し、4値を許容する設計とする。

### `forecast_revision_metrics`とのJOIN例

```sql
SELECT
    eb.code, eb.fiscal_year, eb.metric_name,
    eb.value AS initial_forecast,
    fr.curr_value AS latest_revised_forecast,
    eb_actual.value AS actual_result
FROM earnings_baseline_metrics eb
LEFT JOIN forecast_revision_metrics fr
    ON fr.fiscal_year = eb.fiscal_year AND fr.metric_name = eb.metric_name
    AND fr.consolidation_type = eb.consolidation_type AND fr.period_type = eb.period_type
LEFT JOIN earnings_baseline_metrics eb_actual
    ON eb_actual.code = eb.code AND eb_actual.fiscal_year = eb.fiscal_year
    AND eb_actual.metric_name = eb.metric_name AND eb_actual.period_type = eb.period_type
    AND eb_actual.value_type = 'actual'
WHERE eb.value_type = 'initial_forecast'
```

---

## LLMプロンプト設計

`forecast_revision`のように推論系フィールド（`direct_factors`等）を持たないため、Stage1/Stage2分離は不要。決定論的な表からの数値抽出のみなので**単一コール**（`midterm_plan`の`metrics`抽出と同じ位置付け）とする。

```json
{
    "type": "EARNINGS_BASELINE",
    "data": {
        "fiscal_year_actual": "当期実績の対象決算期（西暦年、数値のみ）",
        "fiscal_year_forecast": "次期の初回業績予想の対象決算期（西暦年、数値のみ）",
        "actual_metrics": [
            {
                "metric_name": "正規化指標名（forecast_revisionと同じルール）",
                "period_type": "'1q'/'2q'/'3q'/'4q'（4q=通期）",
                "consolidation_type": "'consolidated' / 'non_consolidated'",
                "label_raw": "PDF原文のラベル名",
                "value": "当期実績の数値（数値のみ・単位なし）"
            }
        ],
        "initial_forecast_metrics": [
            {
                "metric_name": "正規化指標名",
                "period_type": "'1q'/'2q'/'3q'/'4q'（4q=通期）。同一fiscal_yearで複数のperiod_typeが同時開示される場合はそれぞれ別要素として列挙（例: 通期予想と第1四半期予想が併記されるケース）",
                "consolidation_type": "'consolidated' / 'non_consolidated'",
                "label_raw": "PDF原文のラベル名",
                "value": "次期初回予想の数値（レンジの場合は下限）",
                "value_upper": "レンジの上限（レンジでない場合はnull）"
            }
        ]
    }
}
```

- `metric_name`正規化ルール・`consolidation_type`判定ルールは`forecast_revision.md`のものをそのまま流用する（表記がほぼ同一のため）
- 決算短信サマリー表（経営成績・次期の見通し）から抽出する旨をプロンプトに明記する
- **業種固有の指標名（保険業等）は既存の正規化ルールで最も近いものにマッピングする**：サンプルPDF検証で、保険会社（ＭＳ＆ＡＤ・東京海上）が「保険収益」「税引前利益」「当期利益」のみを開示し「売上高」「営業利益」「経常利益」に相当する行を持たないことを確認した。無理に新しい`metric_name`区分を作らず、`保険収益`→`sales`、`税引前利益`→`ordinary_income`、`当期利益`（親会社帰属分）→`net_income`のように**性質が近いものへ寄せて正規化**する方針とする（`label_raw`に原文ラベルを残すので、後から業種別の厳密な区別が必要になれば`label_raw`から再分類できる）

---

## パイプライン構成

既存パターン（`midterm_plan_analysis`/`forecast_revision_analysis`）を踏襲し、新パッケージ `earnings_baseline_analysis/`（仮称）を作成する。

```
earnings_baseline_analysis/
├── main.py
├── models/
│   ├── earnings_baseline.py         # earnings_baselines テーブル
│   └── earnings_baseline_metric.py  # earnings_baseline_metrics テーブル
└── usecase/
    ├── get_tdnet_earnings_baseline_data.py   # 「決算短信」含み・「四半期」「訂正」「一部」「中間」除外＋Brands.market絞り込みでIR取得
    ├── post_earnings_baseline.py             # SQLiteへの保存
    └── notify_earnings_baseline_corrections.py  # 除外した訂正告知の日次Slack通知

buyback_analysis/prompts/
└── earnings_baseline_native.md  # ネイティブPDF方式のみ（理由は下記）
```

> **テキスト方式を作らずネイティブPDF方式のみとした理由**：`gemini-2.5-flash-lite`系はテキストとPDF（画像）のトークン単価が同一で、コスト差はほぼ無視できる（[docs/midterm_plan_design.md](./midterm_plan_design.md) §コスト面で実測済み、20ページPDFでも1件あたり約0.2円）。一方でこの文書は連結/個別・実績/予想が密集した表構造で、キオクシアの検証（§サンプルPDF検証結果）で判明した通りテキスト抽出時に表のレイアウトが崩れて読み違えるリスクがある。コスト面のデメリットがほぼ無い以上、他パイプラインのように`USE_NATIVE_PDF`環境変数でテキスト方式と切り替え可能にする理由がなく、`main.py`もネイティブPDF方式のみの単一経路とする（`USE_NATIVE_PDF`相当の分岐は持たない）。

`interface/`・`get_pdf_data`/`get_pdf_path`・`parse_text_by_llm`/`parse_pdf_by_llm`・`Logger`・`notifier`は`buyback_analysis`を共用する（既存2パイプラインと同じ）。重複チェックは`code`+`url`複合PKで行い、`is_checked`テーブルは使わない（`forecast_revision_analysis`と同じ理由）。

---

## 懸念点（オープンな論点）

1. **対象件数・コスト**：`get_tdnet_earnings_baseline_data.py`実装後に2025-04〜2026-07（約15.5ヶ月）で実測したところ、タイトル条件（決算短信含む・四半期/訂正/一部/中間除外）のみで7,886件、`Brands.market`（プライム/スタンダード/グロース、INNER JOIN）まで絞り込むと**6,286件**だった（旧稿の「7,884件」はmarket絞り込み前の数字だったため修正）。全上場企業が本決算を年1回開示するため、対象範囲（4月以降の一定期間）で改めて事前カウントし、初回バッチのコスト感を確認してから流す
2. **`fiscal_year_actual`と`fiscal_year_forecast`が連続しないケース**：決算期変更（3月期→12月期等）があった企業では単純な+1にならない可能性があるため、両方をLLMに個別抽出させる設計にしている（コード側で`+1`を仮定しない）
3. **稀に残る「中間決算短信」を出す通常市場銘柄（5件確認）**：`market`条件（プライム/スタンダード/グロース）を満たしつつ「中間決算短信」を出す銘柄が実データ上5件存在した。これらは本決算を別途「中間」を含まないタイトルで出しているはずなので、除外しても実害は無い想定だが、運用開始後に対象漏れがないか確認する
4. **IFRS任意適用初年度の二重開示：現状の実装だと「日本基準版が黙って勝つ」**：サンプルPDF検証で、ＭＳ＆ＡＤ・東京海上ともに「日本基準に基づく決算短信を別途公表済み」と本文に明記されているのを確認した。IFRS任意適用の初年度に限り、同一企業・同一fiscal_yearに対しJ-GAAP版とIFRS版の2つの決算短信URLが存在しうる。
   - `earnings_baseline_metrics`の自然キーに`url`を含めない設計（§テーブル設計）のため、この2文書は同じ自然キーを取り合う
   - `post_forecast_revision.py`と同じパターン（detail保存＋metrics全行のINSERTを1トランザクションにまとめ、`IntegrityError`時に`session.rollback()`で丸ごと破棄）を`post_earnings_baseline`にも踏襲する前提で考えると、**開示日が先の文書が保存に成功し、後から来る文書は自然キー衝突でその文書分がまるごと保存失敗になる**（クラッシュはしない。ログに残り「保存失敗」としてカウントされる）
   - TDnetでは日本基準版が先（例: MS&ADは5/20）・IFRS版が後（同6/26）に開示されるため、日次バッチが開示日順に処理する限り**デフォルトでは日本基準版が残り、IFRS版（今後同社が採用していく会計基準）が失敗扱いになる**。データの質としては逆（IFRS版を残したい）が望ましいはずだが、今のままではそうならない
   - 対象件数はごく少数（今回のサンプル5件中2件）と想定されるため、自動判定ロジックを急いで作るより、まずは「パース/判定失敗」ログに出た`code`を目視で確認し、必要ならその企業だけ`RERUN_URLS`でIFRS版を手動優先させる運用で様子を見る
5. **決算season（5月中旬）のピーク日は日次バッチが1日で終わらない**：実測で2026-05-14が479件・05-15が470件・05-13が366件（Brands.market絞り込み後）。`main.py`はGemini呼び出しを逐次処理（並列化なし）で1件あたり約10〜20秒かかるため、ピーク日は単純計算で約2時間を要する。バッチスケジュール（[stock-analysis/docs/batch_schedule.md](../../stock-analysis/docs/batch_schedule.md)の540番）上、同日18:40の`500 post_buyback_data.bat`（PostgreSQLへの全SQLiteテーブル転記）に間に合わない可能性がある。
   - 対応方針：`post_earnings_baseline()`が1件ごとに`commit()`しているため、間に合わなかった分もSQLiteには確定済みで失われない。`main.py`は`DAYS_BACK=5`で直近5日分を毎回再走査し`_already_exists()`で重複をスキップするため、翌日以降のバッチが自動的に残りを拾って処理する。ピーク日の最悪ケース（約2時間）でも翌日の実行開始（24時間後）までに十分収まるため、実行が重複する心配もない
   - 本パイプラインの用途（初回予想→修正→実績の推移分析）はリアルタイム性を要さないため、ピーク日に限り「PostgreSQL反映が最大1日遅れる」ことを許容する運用とし、並列化などのコード変更は行わない

---

## サンプルPDF検証結果（2ページ制限の妥当性確認）

標準ケース（パソナ2168・ＣＳランバー7808）とIFRS採用企業（アサヒ2502・ＭＳ＆ＡＤ8725・東京海上8766）、計5件のPDF先頭2ページをテキスト抽出して確認した。

- 5件とも経営成績（当期実績）・次期業績予想・配当の状況は先頭2ページに収まっていた（元PDFは17〜35ページ）。**2ページ制限は妥当**
- 連結＋非連結（個別）の同時開示は「(参考)個別業績の概要」として2ページ目に含まれる形で確認でき、`consolidation_type`での区別は想定通り機能しそう
- 上記の`period_type`列追加・業種別指標マッピングの2点は、いずれもこの検証で判明した
- 追加確認（キオクシアホールディングス2026年3月期・IFRS）：次期業績予想に**第1四半期単体の予想**が併記されるケースを確認し、`period_type`の値域を`2q`/`4q`の2値から`1q`/`2q`/`3q`/`4q`の4値に拡張した（詳細は§テーブル設計の該当注記を参照）。また同社は本文中の「次期業績予想」テーブルがPDFテキスト抽出時にレイアウト崩れで注記事項の直前に出現するなど、表構造がテキスト順序と一致しないケースがあることも確認した。ネイティブPDF方式（`MIDTERM_USE_NATIVE_PDF`/`BUYBACK_USE_NATIVE_PDF`と同様の`_native`プロンプト）ではレイアウト情報を保持したまま渡せるため、こうしたケースの取りこぼしを減らせる可能性がある

---

## 実装の推奨順序

1. `earnings_baseline_analysis`パッケージの骨格作成（models・usecase・main.py）
2. `earnings_baseline_native.md`プロンプト作成、5〜10件で精度確認（特に`fiscal_year_actual`/`fiscal_year_forecast`の年度抽出とレンジ処理）
3. `get_tdnet_earnings_baseline_data`（Brands結合込み）で対象件数を事前カウントし、想定コストを確認
4. `notify_earnings_baseline_corrections`（訂正告知の日次Slack通知）を実装
5. 4月以降のデータで日次差分運用を開始
6. `forecast_revision_metrics`とのJOINで初回予想→修正→実績の一本の線が作れることをサンプルで確認
7. 運用が安定したら過去データのバックフィル（①）を別タスクとして検討
