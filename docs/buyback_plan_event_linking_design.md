# 自社株買い案件・イベント紐づけ設計 Phase 1

## 1. 目的と範囲

現行の「1文書を1種別として保存する」処理を、次へ移行する。

```text
TDnet原文書
  └─ 採用抽出版（1文書から複数イベント）
       └─ イベントごとの案件紐づけ判定
            └─ LINKEDイベントだけから案件集計を生成
```

Phase 1は、複数イベント抽出、冪等保存、`new_plan`による案件生成、
`LINKED` / `UNRESOLVED` / `AMBIGUOUS`判定、未確定イベントの再判定及び案件集計を扱う。

`LINKED`済み紐づけの自動訂正とcorrection適用は
[Phase 2設計](buyback_plan_link_correction_design.md)、下流契約は
[handoff](handoffs/buyback-plan-event-linking-contract.md)へ分離する。

本番DB更新、過去文書の一括LLM再抽出、同期、サイト反映は対象外とする。

## 2. 選択肢

### 案A: 既存テーブルへ`buyback_plan_id`を追加

変更は小さいが、1 URLが1行のままで「旧案件完了＋新規案件設定」、未確定イベント、
抽出と紐づけの独立した版管理を表現できないため不採用とする。

### 案B: イベントと案件を分離（採用）

既存テーブルを互換用途として残し、イベント、案件、判定、集計を追加する。
必須要件を満たす最小構造であり、既存の原典・版管理は再実装しない。

## 3. 既存`tdnet_provenance`との関係

新しい文書台帳は作らず、次を再利用する。

- 原文書: `tdnet_source_documents`
- hash照合と`source_conflict`: `resolve_verified_source()`
- LLM runと出力再利用: `processing_runs` / `run_outputs`
- URL単位の抽出結果版と採用: `result_versions` / `result_adoptions`

Phase 1の自己株買い抽出は`TDNET_PROVENANCE_ENABLED=true`を前提とし、
`run_llm_stage()`を経由する。現行RERUNの`origin=unrecorded`経路は新経路に使わない。

`result_type`は版付きの専用値（例: `buyback_events_v1`）とし、1 URLのイベント集合を
`result_versions.payload`へ保存する。イベントテーブルに独自の抽出版有効期間を重複保持しない。

## 4. 複数イベント抽出

### 4.1 フロー

新経路では`ir_type.md`による単一分類と汎用`parse_*_by_llm()`を使わない。
既存経路は移行完了まで互換用途として残す。

```text
verified PDF/text
  -> extract_buyback_events（LLM Stage 1）
  -> schema validation / normalization
  -> result_versionsへイベント集合を保存・採用
  -> deterministic link rules（LLMなし）
  -> plan projection
```

### 4.2 responseSchema

`BuybackEventExtraction.events`を配列とし、各イベントは次を持つ。

- `event_type`
- `event_date`、`resolution_date`
- `referenced_document_date`、`referenced_document_title`
- `source_quote`、`source_page`、`source_section`
- 種別別`payload`

`resolution_date`は本文でイベントの根拠として明示された決議日、
`referenced_document_date`は本文が参照する別文書の開示日として区別する。紐づけの決議日照合は
`resolution_date`を利用し、別文書の開示日参照が明示された場合は`referenced_document_date`も
利用する。
`amendment.resolution_date`には変更元の取得決議日を入れ、変更を決めた日付は`event_date`へ
入れる。

Phase 1の種別は次とする。

```text
new_plan, amendment, execution_notice, progress, completion, supplement,
equity_compensation, retirement, other_party_transaction, other
```

`correction`はPhase 2で追加する。Phase 1中の訂正文書は新経路で`other`へ変換せず、
現行の`DetectType.CORRECTION`及び`corrections`保存経路を維持する。Phase 2開始時に、
原典照合済みPDFを新しいcorrection schemaで再抽出する。

payloadはPydanticで型固定し、取得枠、実績、期間、方法、amendmentの変更前後、
execution noticeのsubtypeを表現する。

`source_page`等はLLM出力なのでIDに使わない。`source_quote`は原文内の存在を機械確認し、
確認できない引用は確定根拠にしない。

### 4.3 LLM stage契約

抽出関数は`GENERATION_CONFIG`（response schema、`temperature=0`）、
`EXTRACTOR_VERSION`、`report_llm_response()`を備える。text/native PDFを別バージョンとし、
`run_llm_stage(stage="events")`経由で呼ぶ。既存`run_llm()`の契約どおり、LLM runは
`run_kind="extract"`として記録される。

## 5. Phase 1データモデル

### `buyback_plans`

| 列 | 内容 |
|---|---|
| `buyback_plan_id` | 不変UUID、PK |
| `code` | 銘柄コード |
| `origin_event_uid` | 起点`new_plan`の論理ID、一意 |
| `lifecycle_status` | `ACTIVE` / `INVALIDATED_ORIGIN` |
| `created_at` | 作成日時 |

### `buyback_events`

採用中のイベントを検索・紐づけする現在テーブル。旧版全文は`result_versions`にある。

| 列 | 内容 |
|---|---|
| `event_uid` | 論理イベントID、PK |
| `version_id` | 採用`result_versions.version_id` |
| `url` / `code` | 原文URL、銘柄 |
| `event_type` | 種別 |
| `event_fingerprint` | 正規化内容hash |
| 文書題名・日付・引用・payload | 原文メタデータ及び抽出値 |
| `source_quote_verified` | NFKC・空白除去後10文字以上の原文内引用一致。falseは保存するが確定根拠にしない |
| `is_active` | 現在の採用版に存在するときtrue |

再抽出で`source_quote_verified`がtrueからfalseへ変わった場合は内容変更と同様に安全失効し、
通常判定をやり直す。引用だけを理由に既存の`LINKED`を維持しない。

### `buyback_event_link_decisions`

候補と判断を1テーブルにまとめ、append-onlyで保存する。

| 列 | 内容 |
|---|---|
| `decision_id` / `event_uid` | 判定、対象イベント |
| `status` | `LINKED` / `UNRESOLVED` / `AMBIGUOUS` |
| `decision_kind` | `NORMAL` / `EXPIRATION` |
| `linked_plan_id` | `LINKED`時だけ非NULL |
| `candidates` | 候補ID、成立根拠、不足根拠、矛盾のJSON配列 |
| `reason_codes` | 最終理由 |
| `rule_version` / `input_fingerprint` | 通常判定の版・入力hash。失効時は専用値・NULL |
| `decided_at` / `supersedes_decision_id` / `is_current` | 履歴管理 |

`decision_kind=NORMAL`の行だけを対象に
`event_uid + rule_version + input_fingerprint`を一意にし、同じ判定を増やさない。同じ入力の
過去decisionを再び現行にする場合はINSERTせず、その行へ現行ポインタを付け替える。
SQLiteでは通常判定の冪等性を部分一意インデックス
`WHERE decision_kind = 'NORMAL'`、イベントごとの現行行を別の部分一意インデックス
`WHERE is_current = 1`で制約する。

安全失効は`decision_kind=EXPIRATION`、`rule_version="expire:v1"`、
`input_fingerprint=NULL`とし、通常判定の一意制約と再判定スキップ条件から除外する。
`EXPIRATION`は常に`status=UNRESOLVED`、`linked_plan_id=NULL`とする。
理由コードは内容変更時`EXPIRED_BY_CONTENT_CHANGE`、イベント消失時`EXPIRED_BY_REMOVAL`、
起点失効の連鎖時`EXPIRED_BY_ORIGIN_INVALIDATION`とする。

### `buyback_plan_projections`

現行`LINKED`イベントから、当初値、現在値、累計、完了実績、案件状態を導出する。
入力イベントfingerprint、集計ルール版、計算日時を持つ。projectionはキャッシュである。
案件ごとに1行とし、起点`new_plan`から当初値、`amendment`を有効日順に適用した現在値、
最新の`progress`累計値、最新の`completion`最終値を保持する。案件が`ACTIVE`で起点が現行
`LINKED`の場合だけ`is_publishable=true`とする。

## 6. イベントIDと冪等性

LLMの配列順、source locator、extractor versionをIDに含めない。

1. 種別別に抽出値を正規化して`event_fingerprint`を作る。
2. 同一URLの旧採用版と新採用版を決定論的に対応付ける。
   比較対象には`is_active=false`の過去イベントも含め、完全一致した場合は旧`event_uid`を
   引き継いで再び`is_active=true`にする。
3. 一意に対応すれば旧`event_uid`を引き継ぐ。
4. 値による一致がなくても、同一URL内の同一種別について旧・新の未対応イベントが
   それぞれ1件だけなら、値の訂正とみなして旧`event_uid`を引き継ぐ。
5. 対応しなければ新UUIDを発行する。
6. 複数の旧イベントに一致する場合は推測せず新IDとし、対応未確定を記録する。

例として、`new_plan`は決議日・正規化取得枠・期間、`progress`は報告期間・累計値、
`completion`は参照決議日・取得期間・最終値を識別属性とする。同値イベントの区別には
正規化前の引用hashを補助利用する。

案件は`origin_event_uid`の一意制約で冪等生成するため、抽出器更新後も案件IDを維持できる。

`new_plan`の同一性は正規化した決議日と、当初の取得株数、取得金額、開始日、終了日で判定する。
両方に値がある属性だけを比較し、1項目以上が一致して矛盾がなければ同一、比較可能な属性が
なければ保留、明示的な不一致があれば別案件とする。同一run内の同一イベント群は開示日時、
URL、`event_uid`順で並べるが、正本候補は競合なしの`new_plan`確定条件を満たすイベントに限る。
その先頭だけが案件を生成し、残りは次runで既存案件へリンクする。案件との比較はamendment適用後の
現在値ではなく起点`new_plan`の当初値を使う。根拠不足の再掲イベントは、既存案件と取得条件が
一致しても自動で`LINKED`に昇格させない。

`adopt_result()`の`write_current`コールバック内で、旧採用イベントとの対応付け、
`event_uid`引継ぎ、現在イベント置換、消失イベントの失効を行う。採用切替に失敗した場合は、
旧採用版、旧イベント及び旧判定を維持する。

新採用版に対応先がない旧イベントは`is_active=false`にし、現行decisionを削除又は空欄には
せず、`EXPIRED_BY_REMOVAL`の現行失効decisionを追記する。
`EXPIRED_BY_REMOVAL`は終端状態とし、そのイベントが後続の採用版で再びactiveにならない限り
通常判定を行わない。
そのイベントが`new_plan`の起点なら、案件を削除せず`INVALIDATED_ORIGIN`へ変更し、
projectionを公開対象外にする。新IDとなった`new_plan`は別の案件候補として判定する。

`event_uid`を引き継いでも`event_fingerprint`が変わった場合、旧`LINKED`判定を新しい値へ
流用しない。Phase 1では安全側に`UNRESOLVED`の失効decisionを追加し、再判定が完了するまで
そのイベントを集計から除外する。これは内容変更時の安全失効であり、別案件への自動訂正は
Phase 2に残す。

起点`new_plan`が内容変更で安全失効した場合、又は案件が`INVALIDATED_ORIGIN`になった場合は、
その案件へ現在`LINKED`しているprogress、completion、amendment等にも
`EXPIRED_BY_ORIGIN_INVALIDATION`を追記する。起点が再確定するまで案件projectionを公開せず、
配下イベントは次のrunで通常判定をやり直す。これにより当初値のない案件へ実績だけが残る
状態を作らない。

## 7. 状態と`new_plan`

| 状態 | 条件 | 集計 |
|---|---|---|
| `LINKED` | 必須根拠を満たす候補が一つで除外矛盾なし | 反映 |
| `UNRESOLVED` | 候補0件、又は候補1件でも必須根拠不足 | 非反映 |
| `AMBIGUOUS` | 成立候補が2件以上 | 非反映 |

LLM confidenceは状態決定に使用しない。

`new_plan`は、会社自身の独立取得決議、決議日、案件識別可能な取得枠又は期間があり、
同一決議との競合がない場合だけ案件を生成し、その案件へ自身を`LINKED`する。
抽出payloadには`company_own_transaction`と`independent_resolution`を三値で保持し、両方が
明示的にtrueの場合だけ根拠成立とする。欠落又はfalseをLLM confidenceで補完しない。
根拠不足は`UNRESOLVED`、同一決議候補が複数なら`AMBIGUOUS`とし、案件を生成しない。
別起点の競合候補が1件だけの場合も自動統合せず`UNRESOLVED`とする。
安全失効した`new_plan`の再判定時に、同じ`origin_event_uid`の案件が既にあれば新規作成せず、
その案件を`ACTIVE`へ戻して再び`LINKED`する。

## 8. 種別別確定条件

| 種別 | `LINKED`の必須条件 | 未確定の代表例 |
|---|---|---|
| amendment | 明示参照、又は決議日と変更前値が一意に一致。変更後値あり | 期間の近さだけ、変更前値が矛盾 |
| execution_notice | 決議参照と方法・枠が一意に整合 | ToSTNeT-3だけ一致 |
| progress | 決議参照又は対象期間が一意、累計値に説明不能な矛盾なし | 同時期に複数案件、参照なし |
| completion | 決議参照、期間又は元文書参照で一意 | 複数案件に同条件で一致 |
| supplement | 対象決議又は元文書への明示参照 | 参照なし。案件は生成しない |
| equity_compensation | 既存取得枠の利用が明示され一意 | 処分・給付のみ。独立決議は別new_plan |
| retirement | 取得案件との関係が明示され一意 | 取得との関係なし |
| other_party_transaction / other | リンク対象外 | 案件を生成・集計しない |

`amendment`は変更後値が少なくとも1項目必要とし、抽出された変更前値が案件の現在値と
矛盾する候補は明示参照があっても除外する。`progress`の対象期間一致は報告期間全体が
案件期間内にあることとし、累計株数・金額が負値又は取得枠超過の候補は除外する。
`UNRESOLVED`の場合も、検討対象となった候補案件IDと不足・矛盾の理由コードをdecisionの
`candidates`へ保存し、追加文書又はルール更新による再判定に利用する。
`execution_notice`は参照決議日の一致に加え、方法又は予定枠が案件の現在条件と一致することを
必要とする。実行実績値は負値又は取得枠超過を矛盾とする。`completion`は最終株数又は金額を
必須とし、参照決議日、案件期間の完全一致、元文書題名の完全一致のいずれかで候補を絞る。
最終値の負値又は取得枠超過は、参照が一致しても確定しない。
`supplement`は参照決議日又は元文書題名の完全一致を必要とする。
`equity_compensation`は`uses_existing_buyback_plan=true`、`retirement`は
`related_to_buyback_plan=true`を明示根拠とし、欠落又はfalseを推測で補完しない。加えて決議日又は
元文書の明示参照で候補を一意にし、株数・金額が負値又は案件枠超過なら確定しない。
`other_party_transaction`及び`other`は常に`EVENT_TYPE_NOT_LINKABLE`として案件候補を持たない
`UNRESOLVED`にし、案件生成及び集計の対象外とする。

日付及びISO 8601開示日時は日付部分の`YYYY-MM-DD`へ、取得方法は`market_purchase`、`tostnet-3`、
`relative_acquisition`等の正規形へ変換してから比較する。正規化関数は紐づけ処理で共用し、
規則変更時はリンクルール版を更新する。

案件候補の現在条件は、`ACTIVE`案件について現行`LINKED`かつ`is_active=true`の起点
`new_plan`から生成し、現行`LINKED`の`amendment`を有効日、`event_uid`の順で適用して導出する。
起点が現行`LINKED`でない案件は候補に含めない。元文書題名は`buyback_events.document_title`へ
原文メタデータとして保持し、参照題名との完全一致に使用する。

「旧案件完了＋新案件設定」は別イベントとして独立保存・判定し、一方の未確定又は失敗で
他方を取り消さない。

## 9. 再判定と収束

Phase 1では`is_active=true`で、通常判定が未確定又は失効判定が現行のイベントだけを
再判定する。`is_active=false`の`EXPIRED_BY_REMOVAL`は対象外とする。トリガーは同一銘柄の
新規案件・イベント、対象イベントの抽出版更新、ルール更新とする。

1. run開始時のsnapshotを固定する。
2. 未確定イベントを各1回判定する。
3. 確定した`new_plan`から案件を生成する。
4. 影響案件のprojectionを各1回再計算する。
5. 同じrun内でprojection変更を再判定トリガーにしない。
6. 新規案件で影響する同一銘柄の別の未確定イベントは、次のrunで再評価する。

`is_active=true`かつ現行decisionが`EXPIRATION`の場合は通常判定対象とする。現行又は過去の
`NORMAL`判定に同じ`input_fingerprint + rule_version`がある場合だけ、新規判定を省略して
その判定を再利用する。失効decisionはこのスキップ条件に含めない。
decisionの追記又は現行切替、案件生成及び影響projection更新は一つのDBトランザクションで
行い、失敗時は直前の現行状態を維持する。
イベント採用による内容変更・消失・起点失効時も、同一銘柄の案件projectionを同じ
トランザクション内で再構築する。

## 10. 集計

現行`LINKED`イベントだけを有効日順に使い、`new_plan`から当初値、amendmentから現在値、
progressから最新累計、completionから完了実績と状態を作る。
未確定、旧decision、旧result versionは使用しない。同じ入力fingerprintとルール版から
同じ結果を生成する。

## 11. 既存データ移行

初期リリースは新規文書を対象とする。過去データは別バッチ・別承認とし、次を区別する。

- LLM再抽出なし: 既存行を候補として取り込み、根拠不足は`UNRESOLVED`。
- LLM再抽出あり: 原典照合済みPDFから複数イベントを抽出。コストと結果変動を伴う。

既存`progress`には`resolution_date`がなく、1 URL 1種別行から複数イベントは復元できない。
既存行だけから確定リンクを推測しない。既存テーブルは下流切替まで残す。

## 12. 実装前テスト仕様

- responseSchemaが複数イベントを受理し、旧案件完了＋新案件設定を二イベントにする。
- 引用が原文にない場合は確定根拠にしない。
- run、使用量、extractor version、採用版を記録する。
- 配列順・locator・extractor versionが変わっても対応できた`event_uid`を維持する。
- 同一URL・同一種別が旧新各1件なら、値が変わっても`event_uid`を維持する。
- 内容が変わった`LINKED`イベントは`UNRESOLVED`へ安全失効し、新値を集計しない。
- 安全失効decisionが通常判定の一意制約・スキップ条件を妨げず、次runで再判定される。
- 採用版から消えたイベント、現行判定、起点案件、projectionを失効できる。
- 消えたイベントには現行の失効decisionが残り、現行decision 0件の状態を作らない。
- `is_active=false`の消失イベントは通常判定されず、案件集計にも戻らない。
- 起点失効時に配下の`LINKED`イベントも安全失効し、案件projectionを公開しない。
- 失効起点が同じ`origin_event_uid`で再確定した場合は既存案件を再利用する。
- 新IDの起点案件が確定した後、配下イベントが次runで新案件へ再リンクされる。
- 同一起点から案件を重複生成しない。
- 候補0件及び候補1件・根拠不足は`UNRESOLVED`になる。
- 成立候補複数は`AMBIGUOUS`になる。
- `new_plan`は条件成立時だけ案件生成し、自身をリンクする。
- 文書内の片方が未確定でも他方を保持する。
- 未確定を集計せず、amendment後も当初値を保持する。
- 同じ入力の再判定・再計算は結果や履歴を増やさない。
- 既存decisionを現行へ戻す場合は再利用し、部分一意制約で現行を一つに保つ。
- 判定、案件生成及びprojection更新の途中失敗で旧状態を維持する。

### 固定fixture台帳

実装前にPostgreSQLのTDnet原典からURLを確定し、URL、本文抜粋、期待イベント、候補、
根拠・矛盾、状態、案件数、projectionをコミットする。URLを推測で補わない。

以下は2026-11-16にPostgreSQLの`tdnet`原典から確認した候補URLである。タイトルだけでは
期待イベントを確定せず、fixture化前にPDF本文と原典hashを確認する。

| 銘柄 | 確認目的 | 原典で確認した候補URL |
|---|---|---|
| 6676 | 取得枠変更と買付方法を同一案件へリンク | 起点`140120260513528588.pdf`、`140120261109570128.pdf`、`140120261109570130.pdf` |
| 2146 | 報酬制度文書を独立案件にしない | `140120261113579604.pdf`、`140120261113579610.pdf` |
| 3038 | 決議、ToSTNeT-3、補足資料を分離 | `140120260926540625.pdf`、`140120260928541306.pdf`、`140120260928541315.pdf`、`140120260929542480.pdf` |
| 3350 | 旧案件完了と新規案件を別イベント化 | `140120261013549598.pdf`、`140120261013549603.pdf`、`140120261013550032.pdf` |
| 5449 | 他社・子会社取引を集計除外できるか本文確認 | `140120261104563628.pdf` |
| 6574 | 同日の実在する2案件を分離 | `140120260821524658.pdf`、`140120260821524659.pdf` |
| 6199 | 取得枠変更とToSTNeT文書をリンク | `140120261029558892.pdf`、`140120261029559847.pdf` |

URLの共通prefixは`https://www.release.tdnet.info/inbs/`である。

## 13. 実装順序

1. fixture URLを原典から確定する。
2. 抽出、ID対応、判定、集計の失敗するテストを追加する。
3. provenance接続と複数イベント抽出を実装する。
4. migration、冪等保存、案件生成、判定、再判定、集計を実装する。
5. 対象・全回帰テストとカバレッジを実行する。

各実装、本番DB操作、再抽出、同期、サイト反映は別の作業境界とする。
