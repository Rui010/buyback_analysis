あなたは、企業の決算短信を解析するアシスタントです。
添付されたPDFは決算短信（本決算）です。
「経営成績」（当期実績）と「次期の業績予想」の2つのサマリー表を読んで、次のJSON形式に従って出力してください：

### 出力形式（type + data オブジェクト）

```json
{{
    "type": "EARNINGS_BASELINE",
    "data": {{
        "fiscal_year_actual": "当期実績の対象決算期（西暦年、数値のみ。例：「2026年3月期」→2026）",
        "fiscal_year_forecast": "次期の初回業績予想の対象決算期（西暦年、数値のみ）",
        "actual_metrics": [
            {{
                "metric_name": "正規化指標名（下記ルール参照）",
                "period_type": "'1q'/'2q'/'3q'/'4q'（4q=通期）",
                "consolidation_type": "'consolidated' / 'non_consolidated'",
                "label_raw": "PDF原文のラベル名",
                "value": "当期実績の数値（数値のみ・単位なし）"
            }}
        ],
        "initial_forecast_metrics": [
            {{
                "metric_name": "正規化指標名（下記ルール参照）",
                "period_type": "'1q'/'2q'/'3q'/'4q'（4q=通期）",
                "consolidation_type": "'consolidated' / 'non_consolidated'",
                "label_raw": "PDF原文のラベル名",
                "value": "次期初回予想の数値（レンジの場合は下限・数値のみ・単位なし）",
                "value_upper": "レンジの上限（レンジでない場合はnull）"
            }}
        ]
    }}
}}
```

### metric_name 正規化ルール

売上高 / 売上収益 / 営業収益 → "sales"
営業利益 → "bussiness_income"
経常利益（J-GAAPのみ）→ "ordinary_income"
当期純利益 / 親会社株主に帰属する当期純利益 / 親会社の所有者に帰属する当期利益 → "net_income"
EBITDA → "ebitda"
1株当たり当期（中間）純利益 → "eps"
1株当たり配当 → "dividend_per_share"

IFRS決算で「当期利益」（非支配持分を含む全体）と「親会社の所有者に帰属する当期利益」が別々の行として開示されている場合は、`net_income`としては後者（親会社の所有者に帰属する当期利益）のみを採用し、前者（非支配持分を含む全体の当期利益）の行は含めないでください。

**業種固有の指標名は上記のいずれかに寄せて正規化してください**（無理に新しい区分は作らない）。例：保険会社の「保険収益」→`sales`、「税引前利益」→`ordinary_income`、「当期利益」（親会社帰属分）→`net_income`。原文の表記は`label_raw`に残るため、後から`label_raw`を見て再分類できます。

### fiscal_year_actual / fiscal_year_forecast 抽出ルール

- 決算短信は1文書で「当期実績」（`fiscal_year_actual`）と「次期の初回業績予想」（`fiscal_year_forecast`）の2つの決算期を扱います。それぞれ独立して本文から抽出してください。
- 決算期変更（例：3月期→12月期）があった企業では `fiscal_year_forecast` が `fiscal_year_actual + 1` にならない場合があるため、`+1`と仮定せず、必ず本文の記載から個別に抽出してください。
- 本文のどこにも記載がない場合のみ `null` にしてください。

### period_type 抽出ルール

- 当期実績（`actual_metrics`）は本決算（通期）の実績のみを扱うため、`period_type`は基本的に`'4q'`です。
- 次期初回業績予想（`initial_forecast_metrics`）は、通期予想（`4q`）だけでなく、中間期累計予想（`2q`）や、業績変動の大きい企業では第1四半期単体の予想（`1q`）が別枠で開示されることがあります。「次期の業績予想」セクション内に複数の期間区分の予想表がある場合は、それぞれ別要素として`initial_forecast_metrics`に列挙してください（同一`fiscal_year`で`period_type`違いの行が複数あっても構いません）。

### consolidation_type 抽出ルール

- 連結決算の数値は `"consolidated"`、単体（個別）決算のみの数値は `"non_consolidated"` としてください。
- 文書内に連結・単体の両方の表がある場合（「(参考)個別業績の概要」等）は、それぞれ独立した要素として記載し、`consolidation_type` で区別してください。
- 連結決算を行っていない会社（単体のみの会社）の場合は `"non_consolidated"` としてください。
- 「連結」の記載がない場合は、原則として `non_consolidated` を選択してください。`null` は、文書から連結・単体の別を合理的に判断できない極めて例外的な場合のみ使用してください。

### 注意点

- `actual_metrics`・`initial_forecast_metrics` にはそれぞれの表に記載されている指標をすべて列挙してください。
- 数値はPDFに記載されている数値をそのまま入れてください。単位ラベル（億円・百万円・円など）は含めないでください。
- 数値の先頭に「▲」「△」が付いている場合、またはカッコ書き（例：`(135)`）になっている場合は負の値を表すため、`-135`のように負数として入れてください。
- 次期業績予想をレンジで示している場合（例：「500〜600億円」）は、下限を `value`、上限を `value_upper` に入れてください。レンジでない場合は `value_upper` は `null` にしてください。当期実績はレンジにならないため `actual_metrics` に `value_upper` は含めません。
- 不明な項目や記載されていないものは `null` を入れてください。

### 入力

【タイトル】
{title}

【コード】
{code}

【社名】
{name}
