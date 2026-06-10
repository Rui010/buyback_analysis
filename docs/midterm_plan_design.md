# 中期経営計画 経営指標リスト化 設計メモ

## 概要

TDnetに開示された中期経営計画PDFをLLMに通して、経営指標（売上高・営業利益率・ROEなど）を構造化データとして抽出・保存する。

---

## データ取得元

既存のPostgreSQLの `tdnet` テーブルから「中期経営計画」「中経」「中計」を含むタイトルをフィルタリングする（`get_tdnet_buyback_data.py` と同様のアプローチ）。

---

## テーブル設計

```
midterm_plans
├── code             # 証券コード (PK)
├── url              # ソースURL (PK)
├── plan_name        # 計画名（例: "2025中期経営計画"）
├── plan_start_year  # 計画開始年度
├── plan_end_year    # 計画終了年度（目標年度）
├── disclosure_date  # 開示日
└── metrics          # 経営指標（JSON文字列）
```

### metricsのJSON構造（例）

```json
[
  {"name": "売上高", "value": 500, "unit": "億円", "target_year": 2025},
  {"name": "営業利益率", "value": 10, "unit": "%", "target_year": 2025},
  {"name": "ROE", "value": 12, "unit": "%", "target_year": 2025}
]
```

指標名・単位・数値が企業ごとに異なるため、まず **JSONカラムで生データを保存** し、後から正規化する方針とする。

---

## LLMプロンプト

`prompts/midterm_plan.md` を作成。既存の `prompts/*.md` パターンに倣い、以下の構造のJSONを返させる：

```json
{
  "type": "MIDTERM_PLAN",
  "data": {
    "plan_name": "2025中期経営計画",
    "plan_end_year": 2025,
    "metrics": [
      {"name": "売上高", "value": 500, "unit": "億円", "target_year": 2025}
    ]
  }
}
```

---

## パイプライン構成

**別パイプライン（推奨）**として実装する。現在の main.py と混在させると複雑になるため：

```
  midterm_plan_analysis/
  ├── main.py                        # 中計専用エントリーポイント
  ├── models/midterm_plan.py         # ORMモデル
  └── usecase/
      ├── get_tdnet_midterm_data.py  # 「中期経営計画」含みIR取得
      └── post_midterm_plan.py      # SQLite保存

  # プロンプト・ユーティリティは buyback_analysis を共用
  buyback_analysis/
  ├── prompts/midterm_plan.md        # 中計抽出用プロンプト
  └── interface/
      ├── logger.py / notifier.py    # ログ・Slack通知
      ├── postgresql_engine.py       # DB接続
      ├── sqlite_engine.py
      └── load_prompt_template.py
```

---

## 懸念点と対処方針

### 1. PDFの複数ページ問題

中計PDFは数十〜百ページになることがある。

**対処：**
- Gemini 2.0 Flash は最大100万トークン対応のため、まずそのまま投げて精度を確認する
- 精度が不十分な場合は「財務目標」「数値計画」「KPI」などのキーワードでページを絞り込んでからLLMに渡す
- さらに必要なら2段階処理（1回目でページ特定、2回目で詳細抽出）を検討する

**推奨：** まずそのまま投げ、問題が出てから絞り込みを追加する

---

## ネイティブPDF処理方式の追加（精度改善）

### 背景

現在の処理は `pypdf` でテキストを抽出してからLLMに渡しているが、中計PDFは表・グラフが多く、テキスト抽出で数値が欠落・崩れるケースがある。  
Gemini Files API を使いPDFをそのまま渡す「ネイティブPDF方式」を新たに追加し、用途に応じて使い分けられるようにする。

### コスト面

`gemini-2.5-flash-lite` はテキストと画像（PDF）のトークン単価が同一（$0.10/1Mトークン）。  
PDF1ページ≒258トークンのため、20ページの中計PDFでも1件あたりのコスト差は約0.2円程度。

### 追加するファイル

```
buyback_analysis/
└── usecase/
    ├── get_pdf_data.py        # 既存：ダウンロード＋テキスト抽出
    ├── get_pdf_path.py        # ★新規：ダウンロードのみ（ローカルパスを返す）
    ├── parse_text_by_llm.py   # 既存：テキストをGeminiへ送信
    └── parse_pdf_by_llm.py    # ★新規：PDFファイルをFiles APIでGeminiへ送信

buyback_analysis/
└── prompts/
    ├── midterm_plan.md        # 既存：{content} あり（テキスト方式用）
    └── midterm_plan_native.md # ★新規：{content} なし（ネイティブPDF方式用）
```

### 処理フロー

```
【テキスト方式（既存）】
get_pdf_data(url, date, save_dir)          # ダウンロード＋テキスト抽出
  └─ 内部で get_pdf_path() を呼んでパスを得た後にテキスト抽出（リファクタ）
parse_text_by_llm(title, content, ...)     # テキストをプロンプトに埋め込んで送信

【ネイティブPDF方式（新規）】
get_pdf_path(url, date, save_dir)          # ダウンロードのみ、ローカルパスを返す
parse_pdf_by_llm(title, pdf_path, ...)     # Files APIでPDFをアップロード→送信→削除
```

### `get_pdf_path.py` の責務

- PDFをダウンロードしてローカルに保存する（キャッシュあり）
- ローカルパス（`str`）を返す
- `get_pdf_data.py` はこの関数を内部で呼び出してテキスト抽出を追加する形にリファクタする

### `parse_pdf_by_llm.py` の責務

```python
def parse_pdf_by_llm(
    title: str, pdf_path: str, code: str, name: str, prompt_filename: str
) -> Optional[Dict[str, Any]]:
    # 1. PDFをGemini Files APIにアップロード
    pdf_file = client.files.upload(path=pdf_path, config={"mime_type": "application/pdf"})
    # 2. {content} を持たないプロンプトテンプレートをロード
    prompt = load_prompt_template(prompt_filename, title=title, code=code, name=name)
    # 3. [pdf_file, prompt] のリストで generate_content を呼ぶ
    response = client.models.generate_content(
        model=LlmModel.LLM_MODEL_GEMINI.value,
        contents=[pdf_file, prompt],
    )
    # 4. アップロードファイルを削除
    client.files.delete(name=pdf_file.name)
    # 5. レスポンスをJSONパース（parse_text_by_llm と同様）
```

### 呼び出し側での使い分け（`midterm_plan_analysis/main.py`）

```python
USE_NATIVE_PDF = os.getenv("USE_NATIVE_PDF", "false").lower() == "true"

if USE_NATIVE_PDF:
    pdf_path = get_pdf_path(url, date, PDF_DOWNLOAD_PATH)
    obj = parse_pdf_by_llm(title, pdf_path, code, name, "midterm_plan_native.md")
else:
    content = get_pdf_data(url, date, PDF_DOWNLOAD_PATH)
    obj = parse_text_by_llm(title, content, code, name, "midterm_plan.md")
```

環境変数 `USE_NATIVE_PDF=true` でネイティブPDF方式に切り替え可能とする。

### 実装の推奨順序

1. `get_pdf_path.py` を追加し、`get_pdf_data.py` をリファクタ
2. `parse_pdf_by_llm.py` を追加
3. `midterm_plan_native.md` プロンプトを追加（`{content}` プレースホルダーを除去）
4. `midterm_plan_analysis/main.py` に `USE_NATIVE_PDF` 切り替えを追加
5. 同一PDFで両方式の抽出結果を比較し、精度を確認する

### 2. 同じ企業の複数バージョン管理

企業が複数年度の中計を開示したり、訂正版を出す場合がある。

**対処：**
- URLをPKにすることで自然に別レコードになる（現行の `is_checked` テーブルと同様）
- 訂正版は `corrections` テーブルと同様に訂正元URLを持つカラムで管理する

### 3. 指標名の表記ゆれ

「売上高」「売上収益」「売上」など企業ごとに表記が異なる。

**対処（2段階正規化）：**
1. **抽出フェーズ**：表記そのまま生データとして保存（`"売上収益"`, `"コア営業利益"` など）
2. **正規化フェーズ**：データが溜まった後にLLMでクラスタリング・正規化する

生データを保持しておくことで、後から正規化ロジックを改善できる。

---

## 実装の推奨順序

1. PDFをそのままGeminiに投げ、生の指標名で保存する（シンプルな初期実装）
2. データが溜まったら指標名の正規化を追加する
3. 精度が問題になったらPDFのページ絞り込みを追加する
