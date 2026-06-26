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
| `withdrawn` | 取り下げ・修正通知で無効 | 分類プロンプト |
| `no_targets` | 中計はあるが数値目標なし／別PDFリンクのみ | 分類プロンプト |
| `postponed` | 公表延期お知らせ | 分類プロンプト |

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
    ├─ metricsあり
    │       → extraction_status = "ok" で INSERT
    │
    └─ metricsなし（空リスト or null）
            ↓
            分類プロンプト（classify_midterm.md）でLLM呼び出し
                → "withdrawn" または "no_targets" を返す
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

metricsが空だった文書を分類するプロンプト。`withdrawn` / `no_targets` のいずれかを返す。

```
判定基準:
- 取り下げ・廃止・無効化の通知 → "withdrawn"
- 訂正通知で数値の記載なし     → "withdrawn"
- 中計はあるが定量目標が非記載 → "no_targets"
- 別PDFへのリンクのみ          → "no_targets"
- 公表延期お知らせ             → "postponed"
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

# metrics判定
metrics = obj.get("data", {}).get("metrics")
if metrics:
    post_midterm_plan(..., data=obj, extraction_status="ok")
else:
    status = classify_midterm_by_llm(title, content, code, name)
    post_midterm_plan(..., data=obj, extraction_status=status)
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
