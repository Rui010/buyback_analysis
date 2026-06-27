# extraction_status 対応設計

## 背景・課題

`midterm_plan_analysis` は現状、取得した全PDFを中計本体として扱い、`midterm_plan.md` プロンプトで一律に構造化抽出を試みる。しかし以下のパターンで抽出が失敗・不完全になるケースがある：

| パターン | 問題 |
|---|---|
| 取り下げ通知 | 「取り下げます」数行のみ。metricsが返せない |
| 訂正文書（数値なし） | 変更箇所のみ記載。metricsが返せない |
| 別PDFへのリンクのみ | pypdfが空文字しか抽出できない |
| 訂正文書（数値あり） | メトリクスは取れるが元の開示と競合する |

---

## extraction_status の定義

下流システムの要件に基づき、以下4値を使用する：

| 値 | 意味 | 設定箇所 |
|----|------|----------|
| `ok` | metricsの抽出に成功 | パイプライン（metrics存在確認後） |
| `failed` | PDF取得・LLM抽出の技術的失敗（再試行余地あり） | パイプライン（例外発生時） |
| `withdrawn` | 取り下げ・修正通知で無効 | パイプライン（タイトルキーワード） |
| `no_targets` | 中計はあるが数値目標なし／別PDFリンクのみ | 分類プロンプト |
| `postponed` | 公表延期お知らせ | パイプライン（タイトルキーワード）/ 分類プロンプト |

### 訂正文書の扱い

訂正文書からmetricsが抽出できた場合は `ok` として保存する。  
どのmetricsを採用するかは下流側が開示日・URLを参照して判断する。  
metricsが取れなかった訂正文書は分類プロンプトで `withdrawn` または `no_targets` に振り分ける。

---

## 処理フロー（変更後）

```
PostgreSQL → 対象IR一覧取得

各レコードをループ:
    │
    ├─ 重複チェック（code + url） → 処理済みならスキップ
    │
    ├─ PDF取得（get_pdf_data / get_pdf_path）
    │       失敗 → extraction_status = "failed" で INSERT → next
    │
    ├─ 抽出プロンプト（midterm_plan.md）でLLM呼び出し
    │       LLM失敗 → extraction_status = "failed" で INSERT → next
    │
    ├─ タイトルに「取り下げ」「廃止」「撤回」を含む
    │       → extraction_status = "withdrawn" で INSERT
    │
    ├─ metricsあり（value が null でない要素が1つ以上）
    │       → extraction_status = "ok" で INSERT
    │
    ├─ タイトルに「延期」「見送り」を含む
    │       → extraction_status = "postponed" で INSERT
    │
    └─ 上記いずれにも該当しない（metricsなし・キーワードなし）
            ↓
            分類プロンプト（classify_midterm.md）でLLM呼び出し
                → "withdrawn" / "no_targets" / "postponed" のいずれかを返す
            → extraction_status = 分類結果 で INSERT
```

INSERT は1件につき1回のみ（INSERT → UPDATE パターンは使わない）。

---

## 変更ファイル一覧

### 1. `midterm_plan_analysis/models/midterm_plan.py`

`extraction_status` カラムを追加：

```python
extraction_status = Column(String, nullable=True)  # ok / failed / withdrawn / no_targets
```

### 2. `buyback_analysis/prompts/classify_midterm.md`（新規）

metricsが空だった文書を分類するプロンプト。`withdrawn` / `no_targets` / `postponed` のいずれかを返す。  
タイトルキーワードで `withdrawn` / `postponed` が確定しなかった場合にのみ呼ばれる。

```
判定基準:
- 取り下げ・廃止・無効化の通知               → "withdrawn"
- 策定に関するお知らせ・計画本体だが数値なし → "no_targets"
- 訂正通知で数値なし                         → "no_targets"
- 別PDFへのリンクのみ                        → "no_targets"
- 「延期」「見送り」表現で計画内容がない     → "postponed"
```

出力形式：
```json
{
    "extraction_status": "withdrawn"
}
```

### 3. `buyback_analysis/usecase/classify_midterm_by_llm.py`（新規）

`parse_text_by_llm()` と同様の構造で、`classify_midterm.md` を呼び出し `extraction_status` 文字列を返す関数。

```python
def classify_midterm_by_llm(
    title: str, content: str, code: str, name: str
) -> str:
    """
    metricsが空だった文書を分類する。
    Returns: "withdrawn" | "no_targets" | "postponed" | "failed"（LLMエラー時）
    """
```

### 4. `midterm_plan_analysis/usecase/post_midterm_plan.py`

`extraction_status` を引数で受け取り、ORMモデルにセットする。

```python
def post_midterm_plan(
    session, data, code, url, disclosure_date, extraction_status
):
    ...
    instance = MidtermPlan(
        ...
        extraction_status=extraction_status,
    )
```

### 5. `midterm_plan_analysis/main.py`

フロー変更の主要箇所：

```python
# PDF取得失敗
if content is None:
    post_midterm_plan(..., data={}, extraction_status="failed")
    failed_pdf += 1
    continue

# LLM抽出
obj = parse_text_by_llm(...)
if obj is None:
    post_midterm_plan(..., data={}, extraction_status="failed")
    failed_parse += 1
    continue

# タイトルキーワード・metrics でステータス確定、どれにも該当しない場合のみLLMで分類
WITHDRAWN_KEYWORDS = ["取り下げ", "廃止", "撤回"]
POSTPONED_KEYWORDS = ["延期", "見送り"]
metrics = obj.get("data", {}).get("metrics")
has_metrics = bool(metrics) and any(m.get("value") is not None for m in metrics)

if any(kw in title for kw in WITHDRAWN_KEYWORDS):
    extraction_status = "withdrawn"
elif has_metrics:
    extraction_status = "ok"
elif any(kw in title for kw in POSTPONED_KEYWORDS):
    extraction_status = "postponed"
else:
    extraction_status = classify_midterm_by_llm(title, content or "", code, name)

post_midterm_plan(..., data=obj, extraction_status=extraction_status)
```

---

## metricsなし判定の基準

`metrics` が以下のいずれかの場合に分類プロンプトへ進む：

- `None`
- `[]`（空リスト）
- リスト内の全要素が `value: null`

---

## 追加コスト

分類プロンプトが走るのは metricsが空だった件数のみ。  
通常の中計PDF（metricsあり）には追加コストは発生しない。
