# forecast_revision_analysis 追加設計書 - LLM抽出パイプライン再設計（Stage1/Stage2分離）

version 0.1（案）2026-07-02

---

## 0. 背景・問題認識

現行実装（[buyback_analysis/usecase/parse_text_by_llm.py](../buyback_analysis/usecase/parse_text_by_llm.py)・[buyback_analysis/prompts/forecast_revision.md](../buyback_analysis/prompts/forecast_revision.md)、詳細は [docs/forecast_revision.md](./forecast_revision.md) §8）は以下の構成になっている。

- 抽出系フィールド（`prev_forecast_date`/`value_unit`/`periods[]`/`reason_raw`）と推論系フィールド（`direct_factors`/`structural_vulnerability`/`spillover_conditions`）が単一プロンプト・単一LLMコールで生成されている
- `responseSchema`/`response_mime_type` 未使用。JSON形式はプロンプト内のテキスト指示のみで担保し、` ```json ` フェンス除去＋`json.loads()` でパースしている（[parse_text_by_llm.py:60-64](../buyback_analysis/usecase/parse_text_by_llm.py#L60-L64)）
- `is_modified` は実際には [post_forecast_revision.py:126](../forecast_revision_analysis/usecase/post_forecast_revision.py#L126) で `prev_value == curr_value` からコード側で再計算されており、LLMが返す `is_modified` は保存処理では使われていない。**ただし** [forecast_revision_analysis/main.py:40-46](../forecast_revision_analysis/main.py#L40-L46) の `_determine_extraction_status()` は生のLLM出力の `is_modified` をそのまま見て `ok`/`no_periods` を判定しており、ここにLLMの判断揺れが混入している
- `direct_factors` 等の選定基準（何件・何を根拠に選ぶか）がプロンプト上曖昧で、実行ごとに結果がブレやすい

これらを解消するため、抽出（決定論的に扱うべきタスク）と推論（判断を伴うタスク）を2段階のLLMコールに分離する。

---

## 1. Stage1 / Stage2 分割設計

```
                          ┌─────────────────────────┐
title/content/code/name → │ Stage1: 抽出（決定論的）  │ → Stage1 JSON
                          │  responseSchemaで型固定  │
                          └─────────────────────────┘
                                      │
                          Stage1出力を要約したコンテキストのみ
                                      ▼
                          ┌─────────────────────────┐
title/code/name/reason_raw│ Stage2: 推論（判断を伴う）│ → Stage2 JSON
+ periods要約            → │  責任範囲を絞った軽量プロンプト │
                          └─────────────────────────┘
                                      │
                          main.py側でマージ（現行shapeを維持）
                                      ▼
                          post_forecast_revision() ← 無改修
```

### フィールドの再分類

| フィールド | Stage | 理由 |
|---|---|---|
| `prev_forecast_date` | 1（抽出） | 文書内の日付表現の同定。判断不要 |
| `value_unit` | 1（抽出） | 表ヘッダーの機械的な読み取り |
| `periods[].period_type/fiscal_year/consolidation_type/metric_name/label_raw` | 1（抽出） | enum・正規化ルールに従った機械的分類 |
| `periods[].prev_value/curr_value/*_upper/prev_year_actual` | 1（抽出） | 表の数値読み取り |
| `periods[].is_modified` | **Stage1のスキーマから削除** | 既に `post_forecast_revision.py` がコードで再計算済み。LLMに聞く意味がない |
| `reason_raw` | 1（抽出） | 原文をそのまま引用するだけの逐語抽出。Stage2の入力としてもそのまま使える |
| `direct_factors` | 2（推論） | 「何が直接要因か」の重み付け判断 |
| `structural_vulnerability` | 2（推論） | 企業構造に関する一般化・推論 |
| `spillover_conditions` | 2（推論） | 他社への外挿・類推 |

---

## 2. Stage1: responseSchemaによる型固定

`google-genai` SDK の `config={"response_mime_type": "application/json", "response_schema": <Pydanticモデル>}` を用いて出力を厳密なJSON Schemaに拘束する。設計イメージ（実装ではない）:

```python
class PeriodType(str, Enum):
    Q1 = "1q"; Q2 = "2q"; Q3 = "3q"; Q4 = "4q"

class ConsolidationType(str, Enum):
    CONSOLIDATED = "consolidated"
    NON_CONSOLIDATED = "non_consolidated"

class MetricName(str, Enum):
    SALES = "sales"
    BUSSINESS_INCOME = "bussiness_income"  # 既存typoを踏襲（DB側の値と一致させる）
    ORDINARY_INCOME = "ordinary_income"
    NET_INCOME = "net_income"
    EBITDA = "ebitda"
    EPS = "eps"
    DIVIDEND_PER_SHARE = "dividend_per_share"

class PeriodExtraction(BaseModel):
    period_type: PeriodType
    fiscal_year: Optional[int] = None
    consolidation_type: Optional[ConsolidationType] = None
    metric_name: MetricName
    label_raw: str
    prev_value: Optional[float] = None
    prev_value_upper: Optional[float] = None
    curr_value: Optional[float] = None
    curr_value_upper: Optional[float] = None
    prev_year_actual: Optional[float] = None

class Stage1Extraction(BaseModel):
    prev_forecast_date: Optional[str] = None
    value_unit: Optional[str] = None
    periods: List[PeriodExtraction]
    reason_raw: Optional[str] = None
```

これにより次が解消される。

- `period_type`/`consolidation_type`/`metric_name` が enum 外の値を返すこと自体が構造上不可能になる
- 数値フィールドに文字列（カンマ区切りや単位付き表記）が紛れ込むことを型レベルで防げる（現状 `_to_float`/`_to_int` はエラーを握りつぶして `None` に変換する対症療法になっている）
- `fiscal_year`/`consolidation_type` は `Optional` のまま維持（本文未記載の正当なケースがあるため `null` 許容は変えない）

Stage2の出力構造も `responseSchema` で固定する。

```python
class Stage2Inference(BaseModel):
    direct_factors: List[str]            # 上限5件（schema上 maxItems で表現できるかはSDK仕様を実装時に要確認）
    structural_vulnerability: List[str]  # 上限3件
    spillover_conditions: List[str]      # 上限3件
```

内容の「正しさ」は判断依存のため、responseSchemaで担保できるのはあくまで**構造**であり、Stage1ほどの決定論性は原理的に得られない点に注意。

---

## 3. Stage1出力 → Stage2コンテキストの受け渡し設計

**Stage2にはStage1の生JSONではなく、要約テキストを渡す。PDF本文（`content`）・PDFファイルそのものは再送しない。**

理由:

- `direct_factors` 等はいずれも「修正理由（`reason_raw`）」を起点に判断すべき項目であり、PDF全文を再度読ませる必要性は薄い
- ネイティブPDF方式（`FORECAST_REVISION_USE_NATIVE_PDF=true`）ではPDFファイル再アップロード分のコスト・レイテンシが単純に2倍になってしまう。Stage1で抽出済みの情報に絞ることでこれを避ける

Stage2プロンプトへの入力例（Stage1結果からmain.py側で機械的に整形）:

```
【企業】{name}（{code}）
【タイトル】{title}
【前回予想公表日】2026-02-13
【修正内容】
- 売上高（連結・2026年3月期第2四半期）: 594,000 → 778,000（+31.0%）
- 営業利益（連結・2026年3月期第2四半期）: 92,000 → 174,000（+89.1%）
- 売上高（連結・2026年3月期通期）: 1,243,000 → 1,462,000（+17.6%）
- 営業利益（連結・2026年3月期通期）: 211,000 → 310,000（+46.9%）
【修正理由（原文）】
情報通信事業において当初計画では想定していなかったハイパースケーラーからの...
```

- 「修正内容」は `is_modified=1`（コード側再計算値）の period のみを対象とし、`change_pct`（`post_forecast_revision.py` の `_calc_change_pct()` と同じ計算）を含めて重要度判断の材料をコード側で用意する
- この整形はLLMには行わせず、orchestration層（main.py）が担う

**懸念点（要検証）**: `reason_raw` に含まれない周辺情報（PDF内の事業セグメント説明など）が `structural_vulnerability` の質に必要な場合、要約コンテキストのみでは現行の「PDF全文を読んだ上での推論」より質が落ちる可能性がある。§7の精度検証で現行実装との出力比較を行い、劣化が見られる場合のみ `content` の一部を Stage2 入力に追加する対応を検討する。

---

## 4. 既存テーブル・既存コードへの影響

**結論: `forecast_revision_details` / `forecast_revision_metrics` ともにスキーマ変更は不要。`post_forecast_revision.py`・`check_missing_fields()` も無改修。**

`post_forecast_revision()` は「`{"type": "FORECAST_REVISION", "data": {...}}` 形式の辞書を受け取る」という契約のみに依存している。main.py 側で Stage1・Stage2 の結果をマージし、現行と同一shapeの `data` 辞書を組み立てて渡せば保存層は一切変更不要。

変更が必要なのは以下のみ。

- **main.py の呼び出し順序**（Stage1呼び出し → Stage2用コンテキスト整形 → Stage2呼び出し → マージ）
- **`_determine_extraction_status()`**: LLM出力の `is_modified` ではなく、`post_forecast_revision.py` と同じ `prev_value == curr_value` 比較のロジックで判定するよう変更する（§6）
- **新規usecase関数の追加**: `extract_forecast_revision_stage1`/`infer_forecast_revision_stage2`/`build_stage2_context`/`merge_stage_results` を `forecast_revision_analysis/usecase/` 配下に追加する。forecast_revision固有のPydanticスキーマを持つため、buyback/midterm と共用している汎用の `parse_text_by_llm`/`parse_pdf_by_llm`（[buyback_analysis/usecase/](../buyback_analysis/usecase/)）には置かない
- **プロンプトファイルの分割**: `forecast_revision.md` を Stage1用・Stage2用の2本に分割する（ネイティブPDF方式用の `_native` バリアントも同様に分割）

```python
stage1_obj = extract_forecast_revision_stage1(title, content, code, name)  # 新規
if stage1_obj is not None:
    stage2_context = build_stage2_context(stage1_obj, title, code, name)   # 新規：機械的な要約整形
    stage2_obj = infer_forecast_revision_stage2(stage2_context)            # 新規
    merged = merge_stage_results(stage1_obj, stage2_obj)                   # 新規：現行shapeへのマージ
else:
    merged = None

# 以降 _determine_extraction_status(merged) / post_forecast_revision(session, merged or {}, ...) は現行のまま
```

### 任意検討事項（MVPでは不要、将来必要になれば追加）

| 追加候補カラム | 用途 | 現時点の判断 |
|---|---|---|
| `stage2_status`（String, nullable） | Stage1成功・Stage2失敗の部分成功を区別 | §5のエラーハンドリング方針で当面は不要と判断。実運用で必要性が生じた時点で追加 |
| `stage1_model`/`stage2_model` | Stage別にモデルを変える場合の記録 | 当面は両Stageとも `gemini-2.5-flash-lite` を使う想定のため不要。既存 `llm_model` カラムで足りる |

現時点では投機的な追加はせず、実装後に本当に必要になった時点でマイグレーションする方針とする。

---

## 5. エラーハンドリング方針（Stage分離に伴う新しい論点）

現行は「LLM呼び出し失敗 → `obj=None` → `extraction_status=failed`」の一本道。Stage分離により新たに「Stage1成功・Stage2失敗」というケースが生まれる。

| ケース | 扱い |
|---|---|
| Stage1失敗（JSON不正・APIエラー上限） | 現行どおり `failed`。`periods`/`metrics` も保存しない |
| Stage1成功・Stage2失敗 | `periods`/`metrics`/`reason_raw` 等Stage1データは保存する。`direct_factors` 等は `null` のまま保存し、`extraction_status` はStage1側の判定結果（`ok`/`no_periods`）をそのまま使う |
| Stage1成功・Stage2成功 | 現行どおり `ok`/`no_periods` |

判断根拠: 540番バッチが外部システムへ転送する主要な価値は `periods`/`metrics`（数値データ）であり、`direct_factors` 等は補助的な定性情報。Stage2の失敗で数値データの保存までブロックするのは退行になる。

リトライは現行踏襲（502/503/504で60秒待機×最大3回、JSON不正でも同様に最大3回）をStage1・Stage2それぞれ独立に適用する。

---

## 6. 決定論性向上のための施策

1. **`is_modified` をLLMに聞くのをやめる**（Stage1スキーマから削除）。`_determine_extraction_status()` を、LLM出力ではなく `prev_value == curr_value` 比較のロジックで判定するよう変更する
2. **`temperature` を明示指定する。** 現行は `config={"max_output_tokens": 16384}` のみで `temperature` 未指定（モデルデフォルト依存）。Stage1は `temperature=0` 相当（決定論重視）、Stage2は再現性とのバランスで低め（例: `0.1〜0.2`）を初期値とし、精度検証時に調整する
3. **`direct_factors` の選定基準をプロンプトで明文化する。** 「`reason_raw` に明示的に記載された事象のみを対象とし、本文に登場する順に列挙する」「一般的な市況コメント・定型的な謝辞等は除外する」のように、判断基準を機械的に再現可能な形に近づける

---

## 7. コスト概算（Gemini 2.5 Flash-Lite、月間300件、PDF平均5ページ）

料金は $0.10 / 1M input tokens、$0.40 / 1M output tokens（2026年5月時点の公表レート）を使用。以下はトークン数の仮定に基づく概算であり、実装後は `response.usage_metadata` の実測値で再計算すること。

### 仮定

| 項目 | 仮定値 | 根拠 |
|---|---|---|
| プロンプト固定部（現行 forecast_revision.md 全体） | 約2,200 tokens | 現行テンプレート約4,000〜4,500文字（和文）から概算 |
| PDF抽出テキスト（5ページ平均） | 約4,500 tokens | TDnet開示PDF1ページあたり和文1,000〜1,500文字程度の想定 |
| 現行出力（periods数件＋reason_raw＋推論3配列） | 約1,500 tokens | JSON構造のオーバーヘッド込み |

### 現行（単一コール）

| input tokens | output tokens | 1件あたり | 月間300件 |
|---|---|---|---|
| 6,700 | 1,500 | (6,700×0.10 + 1,500×0.40)/1,000,000 ≈ **$0.00127** | **≈ $0.38** |

### 新設計（Stage1 + Stage2）

| | input tokens | output tokens | 1件あたり |
|---|---|---|---|
| Stage1（抽出専用・推論指示を除いたプロンプト＋PDFテキスト） | 約6,100 | 約1,000（推論3配列を除いた分軽量化） | (6,100×0.10+1,000×0.40)/1e6 ≈ $0.00101 |
| Stage2（Stage1要約のみ・PDF再送なし） | 約1,700（要約コンテキスト＋Stage2プロンプト） | 約450 | (1,700×0.10+450×0.40)/1e6 ≈ $0.00035 |
| **合計** | | | **≈ $0.00136** |

月間300件: **≈ $0.41**

### 結論

現行 **$0.38/月** → 新設計 **$0.41/月** で、差分は **約 $0.03/月（約8%増）**。Flash-Liteの単価が極めて低いため、この設計変更が絶対額で問題になることはない。増分の主因はコール数が2倍になることによる固定プロンプト部の重複であり、PDF本文をStage2に再送しない設計（§3）によってその増分は最小限に抑えられている。

実運用上のコスト論点はトークン単価ではなく、**レイテンシ**（1件あたりAPIラウンドトリップが1回→2回、レート制限エラー時の最大待機時間が理論上倍になる）と**実装・保守コストの増加**である。ただし月間300件・日次十数件規模では、これも実運用上のボトルネックにはならないと見込まれる。

---

## 8. 移行・検証ステップ

既存の [docs/forecast_revision.md](./forecast_revision.md) §9 精度検証フローに準拠。

1. Step1: 既存の検証セット（デンソー3件・北川精機・フジクラ、計5件）で Stage1/Stage2 分割後の出力を現行実装の出力と突き合わせ、`periods`/`reason_raw` が一致すること、`direct_factors`等の質が劣化していないことを確認
2. Step2: 業種横断20件で `structural_vulnerability`/`spillover_conditions` の質を人手評価（§3の懸念点＝PDF全文を渡さないことによる質の劣化有無を重点確認）
3. Step3: `response.usage_metadata` を数十件分ログ収集し、§7のトークン仮定を実測値で再計算
4. Step4: 問題なければ日次パイプラインに切り替え。既存の `RERUN_URLS` で問題文書を再処理可能（Stage1/Stage2とも再実行される）

---

## 9. 未解決事項（要合意）

- Stage2の入力に`content`（PDF全文）の一部を含めるか否か（§3の懸念点。精度検証の結果次第）
- `direct_factors`等のmaxItems制約をGemini `responseSchema`がPydantic経由でどこまで強制できるか（SDKの挙動は実装時に要確認。強制できない場合はプロンプト指示＋事後トリミングで対応）
- Stage1成功・Stage2失敗時の`extraction_status`表現をこのまま`ok`/`no_periods`で済ませるか、`stage2_status`カラムを追加するか（§4「任意検討事項」）

---

## 10. 変更範囲サマリー

| 項目 | 変わる | 変わらない |
|---|---|---|
| LLMモデル | — | `gemini-2.5-flash-lite`（Stage1/Stage2とも同じ） |
| LLM呼び出し回数 | 1件あたり1回 → 2回 | — |
| `generate_content`の`config` | `response_mime_type`/`response_schema`/`temperature`を追加 | — |
| プロンプトファイル | 1本 → Stage1用・Stage2用の2本に分割 | — |
| PDF取得（`get_pdf_data`/`get_pdf_path`） | — | Stage1で1回のみ呼ぶ（現行と同じ） |
| `main.py`のオーケストレーション | Stage1→整形→Stage2→マージの手順が増える | — |
| `_determine_extraction_status()` | コード計算の`is_modified`を見るよう変更 | — |
| `forecast_revision_details`/`forecast_revision_metrics`（DBモデル） | — | 無変更 |
| `post_forecast_revision.py` | — | 無改修 |
| `check_missing_fields()` | — | 無改修 |
| リトライロジックのパターン | Stage1・Stage2それぞれに独立適用 | パターン自体（502/503/504・60秒×3回）は踏襲 |
