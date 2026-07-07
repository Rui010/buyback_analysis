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

---

## キーワード抽出（別テーブル・2コール分離設計）

### 背景

`metrics`（定量目標）に加えて、中計本文に書かれている戦略テーマ・重点施策（例：DX推進、海外展開、M&A、人的資本経営）もキーワードとして保存したいという要望がある。将来的には「あるテーマに言及している銘柄一覧」「言及が増えているキーワードのトレンド分析」への活用を見込む。

フェーズ1では、キーワードを**自由抽出→生データのまま保存**する方針とする（`metrics`の`name`が正規化せず生表記のまま保存されている既存方針と同じ）。正規化・クラスタリングロジックはデータが溜まってから設計する（フェーズ2）。

### 懸念1: プロンプトの精度劣化

既存の`metrics`抽出プロンプトに`keywords`タスクを追加すると、`metrics`（決定論的な表からの数値抽出）と`keywords`（何を「テーマ」と見なすかの判断を伴う抽出）という性質の異なるタスクが1回のLLMコールに混在し、精度がブレるリスクがある。

この懸念は本リポジトリに実例がある。`forecast_revision_analysis`は元々「抽出系」と「推論系」フィールドを1コールに混在させていたことが原因で出力がブレる問題を抱え、Stage1（抽出・`responseSchema`・`temperature=0`）／Stage2（推論・`temperature=0.2`）の2コールに分離することで解消した（[docs/forecast_revision_llm_pipeline_redesign.md](./forecast_revision_llm_pipeline_redesign.md)）。

**対処**: 同じ2コール分離方針を採用する。既存の`metrics`抽出プロンプト（`midterm_plan.md`/`midterm_plan_native.md`）は無改修とし、`keywords`抽出は別プロンプト（`midterm_keywords.md`/`midterm_keywords_native.md`）・別LLMコールとして新設し`responseSchema`（`MidtermKeywordExtraction`）で型固定する。forecast_revisionのStage2と異なり、キーワードは文書のどこに出現するか分からないため、要約コンテキストだけでなく**PDF本文/PDFファイルを再送する**（コストはFlash-Lite単価では無視できる規模）。

### 懸念2: 保存先テーブル

当初`midterm_plans`テーブルに`keywords`列（JSON文字列）を追加する案を検討したが、以下の理由で**別テーブルに分離**した：

- 本プロジェクトはAlembic等のマイグレーションツールを持たず、`init_db()`は`Base.metadata.create_all()`のみ（既存テーブルへの`ALTER TABLE`は行わない）。既存の`midterm_plans`テーブルには既にデータが入っているため、列追加には本番DBへの手動`ALTER TABLE`が必要になる。新規テーブルなら`create_all()`だけで済み、既存テーブルには一切触れない
- 将来の用途（銘柄横断検索・トレンド分析）と相性が良い。JSON文字列カラムより「1行=1キーワード」の縦持ちテーブルの方がJOIN/GROUP BYで直接使える

### 懸念3: PK設計とcontextの保持（forecast_revision_analysisとの整合）

上記の設計を`forecast_revision_analysis`の既存テーブルと突き合わせたところ、2点の不整合が見つかったため合わせて修正する。

**PK設計**: 当初`midterm_plan_keywords`は`(code, url, keyword)`の複合主キーとする案だったが、`forecast_revision_metrics`は自然キー（`url`/`period_type`/`fiscal_year`/`consolidation_type`/`metric_name`）を複合PKにはせず、`id`（autoincrement）を主キーにして自然キーは`UniqueConstraint`で担保している。これは、CLAUDE.mdに記録されている「`fiscal_year`・`consolidation_type`が無く自然キーが不足していたために重複を検出できない設計上の欠陥があり、後から列を追加した」という経緯（[docs/forecast_revision.md](./forecast_revision.md) §7）を踏まえた設計であり、複合PKよりサロゲートPK＋UniqueConstraintの方が自然キーの拡張に強いという教訓が既にこのリポジトリにある。`midterm_plan_keywords`もまだテーブルが実在しない（作成コストがゼロの）段階のため、同じ構成に揃える。

**context_rawの追加**: `forecast_revision_details.reason_raw`は、修正理由を原文のまま逐語引用して保存し、Stage2がPDF本文を読み返さずに済むようにしている。同じ考え方で、`keyword`だけでなくそれが言及されている一文程度の`context_raw`（原文からの逐語引用）も保存する。フェーズ2の正規化（表記ゆれ吸収・クラスタリング）を行う際、単語だけでは文脈が分からず判断できないという問題への対処であり、命名も`reason_raw`/`label_raw`と同じ`_raw`サフィックス規則に合わせる。

### テーブル設計

```
midterm_plan_keywords
├── id                 # サロゲートPK（autoincrement）
├── code               # 証券コード
├── url                # ソースURL（midterm_plansと対応）
├── keyword            # LLM抽出時の生表記
├── context_raw        # キーワードが言及されている一文程度の逐語引用
├── disclosure_date    # 開示日（集計・トレンド分析用に非正規化して持たせる）
├── normalized_keyword # 正規化後の表記（フェーズ2で使用、当面はNULLのまま）
└── UniqueConstraint(code, url, keyword)  # 自然キー（forecast_revision_metricsと同じ構成）
```

`normalized_keyword`は将来の正規化フェーズで使う列だが、テーブル作成前の今のタイミングで定義しておけばコストはゼロであり、後から追加する場合の同じマイグレーション問題を避けられるため先に定義した。

### responseSchemaの構造

`keywords`は文字列配列ではなく、`keyword`と`context_raw`を持つオブジェクトの配列にする。

```json
{
    "type": "MIDTERM_PLAN",
    "data": {
        "keywords": [
            {"keyword": "DX推進", "context_raw": "全社的なDX推進により業務効率化を図る"},
            {"keyword": "海外展開", "context_raw": "東南アジア地域への事業展開を加速する"}
        ]
    }
}
```

### 運用

- 環境変数`MIDTERM_EXTRACT_KEYWORDS`（デフォルト`false`）で有効化する。精度検証後に有効化する運用とする
- `metrics`抽出が失敗した場合はキーワード抽出を呼ばない（forecast_revisionの「Stage1失敗→Stage2をスキップ」と同じ判断）
- キーワード抽出自体が失敗しても`midterm_plans`側の保存はブロックしない（`post_midterm_keywords`は`keywords=None`を渡された場合は何もしない）
- LLMが同一文書内で同じ`keyword`（完全一致）を重複して返す可能性があるため、`post_midterm_keywords`側で保存前に`keyword`単位の重複除去を行う（先勝ち）。除去しないと`UniqueConstraint(code, url, keyword)`違反でその文書のキーワードが全件ロールバックされてしまうため
- `context_raw`は`Optional[str] = None`とする。テーマが文書内の複数箇所に分散して言及されている等、LLMが単一の引用元を特定できないケースがあり得るため、必須にすると抽出失敗のリスクが上がる

### 懸念4: 過去データへのバックフィル

`main.py`は`_already_exists(session, code, url)`が`True`のURLを即`continue`でスキップする。そのため`MIDTERM_EXTRACT_KEYWORDS`を後から有効化しても、既に`midterm_plans`に保存済みの過去データにはキーワードが後付けされない。

`RERUN_URLS`で代用することも可能だが、tdnetから対象を取り直して削除→全再処理（`metrics`含む）を行う構造のため、過去データの一括バックフィルには次の問題がある：

- 対象URLを自分で列挙する必要があり、大量の過去データには不向き
- `metrics`まで不要に再抽出される（Geminiコストの無駄に加え、既に正しい`metrics`が再抽出結果と微妙にズレるリスクがある）

**対処**: `backfill_keywords.py`というkeyword抽出専用の別エントリーポイントを用意する。

- `get_midterm_plans_missing_keywords()`で、`midterm_plans`から`extraction_status='ok'`かつ`midterm_plan_keywords`に対応行が無いものを、**開示日が新しい順**に`MIDTERM_BACKFILL_KEYWORDS_LIMIT`件（デフォルト50件）取得する
- `midterm_plans`には`title`（開示タイトル）・`name`（企業名）が保存されていないため、対象URL一覧で`get_tdnet_midterm_data_by_urls()`をPostgreSQLに投げて引き直す（`RERUN_URLS`が既に使っている関数を再利用）
- PDFを再取得し、keyword抽出のみ実行（`metrics`には触れない）
- `main.py`とは別のエントリーポイントとし、日次差分処理のロジックには影響を与えない

**LIMITによる制御**: 処理済みの行は次回呼び出し時に自動的に対象から外れる（`NOT EXISTS`の対象でなくなるため）。そのため同じコマンドを繰り返し実行するだけで続きから再開でき、オフセット管理やカーソル保存は不要。開示日が新しい順に処理することで、直近のデータから優先的にキーワードが埋まる。
