# buyback_analysis 追加設計書 - 業績予想修正トラッカー対応

version 2.1　2026-06-29

---

## 1. 概要

既存の buyback_analysis システムに業績予想修正IRの収集・LLM抽出処理を追加する。
`midterm_plan_analysis` と同じアーキテクチャパターンを踏襲し、新パッケージ `forecast_revision_analysis/` を作成する。
`interface/` は持たず、`buyback_analysis/` のユーティリティ群をすべて共用する。

### 既存処理との対応関係

| 既存（midterm_plan_analysis） | 今回追加（forecast_revision_analysis） |
|---|---|
| TDNETから「経営計画」「中計」含みIRを取得 | TDNETから「修正」「業績」含みIRを取得 |
| PDFをLLMでパース | PDFをLLMでパース |
| SQLiteに保存（midterm_plans） | SQLiteに保存（forecast_revision_details / _metrics） |
| 540番バッチで別システムへ転送 | 540番バッチで別システムへ転送（既実装） |

---

## 2. モジュール構成

```
forecast_revision_analysis/
├── __init__.py
├── main.py                                   # エントリーポイント・パイプライン制御
├── models/
│   ├── __init__.py
│   ├── forecast_revision_detail.py           # forecast_revision_details テーブル
│   └── forecast_revision_metric.py           # forecast_revision_metrics テーブル
└── usecase/
    ├── __init__.py
    ├── get_tdnet_forecast_revision_data.py   # PostgreSQLから業績修正IR一覧を取得
    └── post_forecast_revision.py             # SQLiteへの保存
```

プロンプトテンプレートは既存パイプラインと同様 `buyback_analysis/prompts/` に追加:

```
buyback_analysis/prompts/
├── forecast_revision.md         # テキスト方式用（{content} あり）
└── forecast_revision_native.md  # ネイティブPDF方式用（{content} なし）
```

---

## 3. buyback_analysis 共用資産

| 共用モジュール | インポートパス | 用途 |
|---|---|---|
| `get_database_engine` | `buyback_analysis.interface.postgresql_engine` | PostgreSQL接続 |
| `SessionLocal, init_db` | `buyback_analysis.interface.sqlite_engine` | SQLite接続・テーブル初期化 |
| `get_pdf_data` | `buyback_analysis.usecase.get_pdf_data` | PDFダウンロード＋テキスト抽出 |
| `get_pdf_path` | `buyback_analysis.usecase.get_pdf_path` | PDFダウンロードのみ（ネイティブPDF方式用） |
| `parse_text_by_llm` | `buyback_analysis.usecase.parse_text_by_llm` | LLMによるテキストパース |
| `parse_pdf_by_llm` | `buyback_analysis.usecase.parse_pdf_by_llm` | LLMによるネイティブPDFパース |
| `Logger` | `buyback_analysis.interface.logger` | ロガー |
| `notify_success, notify_error` | `buyback_analysis.interface.notifier` | Slack通知 |
| `Base` | `buyback_analysis.models.base` | SQLAlchemy ORMベースクラス |

---

## 4. バッチ構成

### 新規バッチ（530番のみ）

| No | バッチ名 | コマンド | 実行タイミング |
|---|---|---|---|
| 530 | `run_forecast_revision.bat` | `python -m forecast_revision_analysis.main` | 毎日 19:15 |

540番（SQLite→PostgreSQL転送・S3書き出し）は別システムにて実装済み。

### 依存関係

```
120 run_tdnet.bat（17:30）
  ↓
530 run_forecast_revision.bat（19:15）← TDNETデータ必須
  ↓
540 post_forecast_revision.bat（19:45）← SQLite保存済み必須（別システム実装済み）
```

---

## 5. main.py 処理フロー

`midterm_plan_analysis/main.py` と同一パターン。

```python
# 環境変数
DAYS_BACK = int(os.getenv("DAYS_BACK", "5"))
SYSTEM_START_DATE = os.getenv("SYSTEM_START_DATE")       # YYYY-MM-DD
SYSTEM_END_DATE   = os.getenv("SYSTEM_END_DATE")         # YYYY-MM-DD
USE_NATIVE_PDF    = os.getenv("FORECAST_REVISION_USE_NATIVE_PDF", "false").lower() == "true"
RERUN_URLS        = [u.strip() for u in os.getenv("RERUN_URLS", "").split(",") if u.strip()]

# 処理フロー
init_db()                             # ForecastRevisionDetail/Metric のインポートで Base に登録
postgresql_engine = get_database_engine()

if RERUN_URLS:
    # metrics → details の順で削除（子テーブルを先に）
    for url in RERUN_URLS:
        session.query(ForecastRevisionMetric).filter(...url...).delete()
        session.query(ForecastRevisionDetail).filter(...url...).delete()
    session.commit()
    df = get_tdnet_forecast_revision_data_by_urls(postgresql_engine, RERUN_URLS)
else:
    df = get_tdnet_forecast_revision_data(postgresql_engine, start_date, end_date)

for _, row in df.iterrows():
    if _already_exists(session, code, url):  # session.get() で複合PK確認
        skipped_duplicates += 1; continue

    if USE_NATIVE_PDF:
        pdf_path = get_pdf_path(url, date_str, PDF_DOWNLOAD_PATH)
        obj = parse_pdf_by_llm(title, pdf_path, code, name, "forecast_revision_native.md")
    else:
        content = get_pdf_data(url, date_str, PDF_DOWNLOAD_PATH)
        obj = parse_text_by_llm(title, content, code, name, "forecast_revision.md")

    WITHDRAWN_KEYWORDS  = ["取り下げ", "廃止", "撤回"]
    CORRECTION_KEYWORDS = ["訂正"]

    # 取り下げはPDF取得・LLM呼び出しをスキップして記録のみ
    if any(kw in title for kw in WITHDRAWN_KEYWORDS):
        post_forecast_revision(session, {}, code, url, disclosure_date, "withdrawn")
        continue

    if USE_NATIVE_PDF:
        pdf_path = get_pdf_path(url, date_str, PDF_DOWNLOAD_PATH)
        obj = parse_pdf_by_llm(title, pdf_path, code, name, "forecast_revision_native.md")
    else:
        content = get_pdf_data(url, date_str, PDF_DOWNLOAD_PATH)
        obj = parse_text_by_llm(title, content, code, name, "forecast_revision.md")

    if any(kw in title for kw in CORRECTION_KEYWORDS):
        extraction_status = "correction"   # 数値は通常どおり抽出・保存、ステータスで区別
    else:
        extraction_status = _determine_extraction_status(obj)

    saved = post_forecast_revision(session, obj or {}, code, url, disclosure_date, extraction_status)
    if saved and extraction_status == "ok":
        if check_missing_fields(obj or {}, code, url):  # [MISSING] ログ記録・件数カウント
            missing_fields_count += 1

# サマリー例: "総処理:30件 / 保存:28件 / 重複スキップ:0件 / PDF失敗:0件 / パース失敗:2件 / 欠損データ:3件"
notify_success / notify_error("forecast_revision_analysis", summary)
```

### extraction_status 判定

| 値 | 条件 |
|---|---|
| `ok` | `periods` に `is_modified=1` の項目が1件以上ある |
| `no_periods` | LLM応答は得られたが `periods` が空または全件 `is_modified=0` |
| `failed` | `get_pdf_data()`/`parse_text_by_llm()` が `None` を返した |
| `withdrawn` | タイトルに「取り下げ」「廃止」「撤回」を含む（LLM抽出はスキップ） |
| `correction` | タイトルに「訂正」を含む（数値は通常どおり抽出・保存） |

---

## 6. usecase 設計

### get_tdnet_forecast_revision_data.py

`get_tdnet_midterm_data.py` と同一パターン。PostgreSQLから全件取得後、Pandasでタイトルフィルタを適用する。

```python
FORECAST_REVISION_KEYWORDS = ["修正", "業績"]  # AND条件: 両方含む行のみ

def get_tdnet_forecast_revision_data(engine, start_date, end_date):
    # ... SELECT FROM tdnet WHERE date BETWEEN ... ...
    df = pd.read_sql_query(query_text, connection, params=...)
    filtered = df[df["title"].str.contains("修正") & df["title"].str.contains("業績")]
    return filtered

def get_tdnet_forecast_revision_data_by_urls(engine, urls):
    # RERUN_URLS 用（get_tdnet_midterm_data_by_urls と同一実装パターン）
```

### post_forecast_revision.py

`post_midterm_plan.py` と同一パターン。`data.get("data", {})` でLLM応答の内部オブジェクトを取り出す。

#### check_missing_fields()

`extraction_status=ok` のレコードに対して重要フィールドの欠損を検出する関数。欠損があれば `[MISSING] field=... code=... url=...` 形式でログに記録する（URL付きなので grep や ChatGPT への投げ込みが容易）。データは保存済みの状態で呼ぶため保存処理には影響しない。

```python
_PERIOD_REQUIRED_FIELDS = ["metric_name", "label_raw", "prev_value", "curr_value"]

def check_missing_fields(data: dict, code: str, url: str) -> bool:
    """欠損があれば [MISSING] ログを記録し True を返す。"""
    inner = data.get("data", {})
    has_missing = False
    if inner.get("prev_forecast_date") is None:
        logger.info(f"[MISSING] field=prev_forecast_date code={code} url={url}")
        has_missing = True
    for i, period in enumerate(inner.get("periods", [])):
        for field in _PERIOD_REQUIRED_FIELDS:
            if period.get(field) is None:
                logger.info(f"[MISSING] field=periods[{i}].{field} period_type={period.get('period_type')} code={code} url={url}")
                has_missing = True
    return has_missing
```

欠損チェック対象フィールド:

| レベル | フィールド | 欠損時の影響 |
|---|---|---|
| detail | `prev_forecast_date` | 前回予想の公表日が不明 |
| period | `metric_name` | 指標の正規化名が不明・集計不能 |
| period | `label_raw` | PDF原文との対応が取れない |
| period | `prev_value` | 変化率計算不能 |
| period | `curr_value` | 変化率計算不能 |

#### post_forecast_revision()

```python
def post_forecast_revision(
    session: Session,
    data: dict,
    code: str,
    url: str,
    disclosure_date: str,
    extraction_status: str,
) -> bool:
    inner = data.get("data", {})

    detail = ForecastRevisionDetail(
        code=code, url=url,
        disclosure_date=disclosure_date,
        reason_raw=inner.get("reason_raw"),
        direct_factors=json.dumps(inner.get("direct_factors"), ensure_ascii=False),
        structural_vulnerability=json.dumps(inner.get("structural_vulnerability"), ensure_ascii=False),
        spillover_conditions=json.dumps(inner.get("spillover_conditions"), ensure_ascii=False),
        llm_model=LlmModel.LLM_MODEL_GEMINI.value,
        extraction_status=extraction_status,
        extracted_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    session.add(detail)

    for period in inner.get("periods", []):
        prev = period.get("prev_value")
        curr = period.get("curr_value")
        metric = ForecastRevisionMetric(
            url=url,
            period_type=period.get("period_type"),
            metric_name=period.get("metric_name"),
            label_raw=period.get("label_raw"),
            prev_value=prev,
            prev_value_upper=_to_float(period.get("prev_value_upper")),
            curr_value=curr,
            curr_value_upper=_to_float(period.get("curr_value_upper")),
            prev_year_actual=_to_float(period.get("prev_year_actual")),
            change_pct=_calc_change_pct(prev, curr),
            is_modified=0 if prev == curr else 1,  # LLMに依存せずコードで確定
        )
        session.add(metric)

    session.commit()  # IntegrityError は midterm と同様にロールバック処理
```

---

## 7. DB設計（SQLite / SQLAlchemy ORM）

### forecast_revision_detail.py

```python
from sqlalchemy import Column, String, Text
from buyback_analysis.models.base import Base

class ForecastRevisionDetail(Base):
    __tablename__ = "forecast_revision_details"

    code                     = Column(String, primary_key=True)
    url                      = Column(String, primary_key=True)
    disclosure_date          = Column(String)
    prev_forecast_date       = Column(String) # 前回予想の公表日（PDF記載がなければnull）
    value_unit               = Column(String) # 財務数値の表示単位（百万円 / 千円）。EPS・配当は対象外
    reason_raw               = Column(Text)
    direct_factors           = Column(Text)   # JSON配列文字列
    structural_vulnerability = Column(Text)   # JSON配列文字列
    spillover_conditions     = Column(Text)   # JSON配列文字列
    llm_model                = Column(String)
    extraction_status        = Column(String) # ok / no_periods / failed / withdrawn / correction
    extracted_at             = Column(String) # SQLiteにDateTime型がないためString。post_forecast_revision() で datetime.now().strftime("%Y-%m-%d %H:%M:%S") をセット
```

### forecast_revision_metric.py

```python
from sqlalchemy import Column, Integer, String, Float
from buyback_analysis.models.base import Base

class ForecastRevisionMetric(Base):
    __tablename__ = "forecast_revision_metrics"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    url                = Column(String, nullable=False)  # forecast_revision_details.url に対応
    period_type        = Column(String, nullable=False)  # '1q'/'2q'/'3q'/'4q'（4q=通期）
    metric_name        = Column(String, nullable=False)  # 正規化指標名（§8参照）
    label_raw          = Column(String)                  # PDF原文ラベル
    prev_value             = Column(Float)   # 前回予想値（レンジの場合は下限）
    prev_value_upper       = Column(Float)   # 前回予想値の上限（レンジでない場合はnull）
    curr_value             = Column(Float)   # 今回修正予想値（レンジの場合は下限）
    curr_value_upper       = Column(Float)   # 今回修正予想値の上限（レンジでない場合はnull）
    prev_year_actual       = Column(Float)   # 前年同期実績値（表に「前年同期実績」列があれば。なければnull）
    change_pct             = Column(Float)   # post_forecast_revision() でコード計算（LLM非依存）
    is_modified            = Column(Integer) # 0=据え置き / 1=修正あり
```

### 重複チェック

`midterm_plan_analysis` と同様に `code + url` 複合主キーで判定する。`is_checked` テーブルは使用しない。

```python
def _already_exists(session, code: str, url: str) -> bool:
    return session.get(ForecastRevisionDetail, {"code": code, "url": url}) is not None
```

> **`is_checked` を使わない理由**
> `is_checked` テーブルは `buyback_analysis` 専用で、`DetectType`（文書種別の分類結果）を紐付けて管理することが主目的。
> `forecast_revision_analysis` は文書種別判定が不要なため、`midterm_plan_analysis` と同様に対象テーブルの複合主キー（`code + url`）で処理済み管理を行う。

### init_db() への登録

`main.py` 冒頭でモデルをインポートするだけで `Base.metadata` に登録される（`midterm_plan_analysis/main.py` の `MidtermPlan` インポートと同じ）。

```python
from forecast_revision_analysis.models.forecast_revision_detail import ForecastRevisionDetail
from forecast_revision_analysis.models.forecast_revision_metric import ForecastRevisionMetric
```

---

## 8. LLM抽出設計

### 使用関数・設定

| 項目 | 内容 |
|---|---|
| テキスト方式 | `parse_text_by_llm(title, content, code, name, "forecast_revision.md")` |
| ネイティブPDF方式 | `parse_pdf_by_llm(title, pdf_path, code, name, "forecast_revision_native.md")` |
| 使用モデル | `LlmModel.LLM_MODEL_GEMINI.value`（= `"gemini-2.5-flash-lite"`） |
| リトライ | 502/503/504 エラー時に 60秒待機×最大3回（`parse_text_by_llm` 内で実装済み） |

### プロンプトテンプレート（forecast_revision.md）

テンプレート変数は `{title}` / `{content}` / `{code}` / `{name}`（既存プロンプトと同一）。
出力形式は `{"type": "FORECAST_REVISION", "data": {...}}` で統一する（`midterm_plan.md` と同一構造）。

```
あなたは、企業の業績予想修正IRを解析するアシスタントです。
「入力」には業績予想修正について書かれています。
それを読んで、次のJSON形式に従って出力してください：

### 出力形式（type + data オブジェクト）

```json
{{
    "type": "FORECAST_REVISION",
    "data": {{
        "prev_forecast_date": "前回予想の公表日（YYYY-MM-DD形式。PDF本文に記載がなければnull）",
        "value_unit": "財務数値の表示単位（PDFの表ヘッダーから取得。例：'百万円'、'千円'）。EPSや配当は対象外",
        "periods": [
            {{
                "period_type": "修正されている期間（'1q'/'2q'/'3q'/'4q'、4q=通期）",
                "metric_name": "正規化指標名（下記ルール参照）",
                "label_raw": "PDF原文のラベル名",
                "prev_value": "前回予想値（レンジの場合は下限・数値のみ・単位なし）",
                "prev_value_upper": "前回予想値の上限（レンジでない場合はnull）",
                "curr_value": "今回修正予想値（レンジの場合は下限・数値のみ・単位なし）",
                "curr_value_upper": "今回修正予想値の上限（レンジでない場合はnull）",
                "prev_year_actual": "前年同期実績値（表に「前年同期実績」列があれば。数値のみ・単位なし。列がなければnull）",
                "is_modified": "修正あり=1、据え置き=0"
            }}
        ],
        "reason_raw": "修正理由の原文をそのまま抽出",
        "direct_factors": ["今回の修正に直接影響した事象（最大5件）"],
        "structural_vulnerability": ["なぜこの企業がその影響を受けやすい構造か（最大3件）"],
        "spillover_conditions": ["同様の影響を受けうる他企業の条件（最大3件）"]
    }}
}}
```

### metric_name 正規化ルール

売上高 / 売上収益 / 営業収益 → "sales"
営業利益 → "bussiness_income"
経常利益（J-GAAPのみ）→ "ordinary_income"
当期純利益 / 親会社株主に帰属する当期純利益 → "net_income"
EBITDA → "ebitda"
1株当たり当期（中間）純利益 → "eps"
1株当たり配当 → "dividend_per_share"

### 注意点

- `periods` には修正された期間・指標の全組み合わせを列挙してください。
- 数値はPDFに記載されている数値をそのまま入れてください。単位ラベル（億円・百万円・円など）は含めないでください。
- 予想をレンジで示している場合（例：「500〜600億円」）は、下限を `curr_value`、上限を `curr_value_upper` に入れてください。レンジでない場合は `prev_value_upper` / `curr_value_upper` は `null` にしてください。
- `prev_forecast_date` は「○年○月○日に公表した」「（○年○月○日発表）」「○年○月○日付」「○年○月○日開示」など前回予想を指す日付表現をすべて候補として探してください。PDFのテキスト抽出で「2026 年１月 14 日」のように文字間にスペースが入る場合でも日付として認識してください。本日の開示日と混同しないこと。令和表記は西暦に変換。記載がなければ `null` にしてください。
- `prev_year_actual` は表の「前年同期実績」列から取得してください。列が存在しない場合は `null` にしてください。数値のみ・単位なしで、EPSや配当を含む全指標で取得してください。
- 不明な項目や記載されていないものは `null` を入れてください。
- `direct_factors` / `structural_vulnerability` / `spillover_conditions` は簡潔な文字列のリストとして抽出してください。

### 入力

【タイトル】
{title}

【本文】
{content}

【コード】
{code}

【社名】
{name}
```

`forecast_revision_native.md` は `{content}` プレースホルダーと「【本文】」セクションを除いた同一内容とする
（`parse_pdf_by_llm` は `load_prompt_template(filename, title=title, code=code, name=name)` で呼ぶため）。

### 期待出力例（フジクラ 2026/6/18）

```json
{
  "type": "FORECAST_REVISION",
  "data": {
    "prev_forecast_date": "2026-02-13",
    "periods": [
      {
        "period_type": "2q",
        "metric_name": "sales",
        "label_raw": "売上高",
        "prev_value": 594000,
        "prev_value_upper": null,
        "curr_value": 778000,
        "curr_value_upper": null,
        "prev_year_actual": 489000,
        "is_modified": 1
      },
      {
        "period_type": "2q",
        "metric_name": "bussiness_income",
        "label_raw": "営業利益",
        "prev_value": 92000,
        "prev_value_upper": null,
        "curr_value": 174000,
        "curr_value_upper": null,
        "prev_year_actual": 71000,
        "is_modified": 1
      },
      {
        "period_type": "4q",
        "metric_name": "sales",
        "label_raw": "売上高",
        "prev_value": 1243000,
        "prev_value_upper": null,
        "curr_value": 1462000,
        "curr_value_upper": null,
        "prev_year_actual": 1009000,
        "is_modified": 1
      },
      {
        "period_type": "4q",
        "metric_name": "bussiness_income",
        "label_raw": "営業利益",
        "prev_value": 211000,
        "prev_value_upper": null,
        "curr_value": 310000,
        "curr_value_upper": null,
        "prev_year_actual": 148000,
        "is_modified": 1
      }
    ],
    "reason_raw": "情報通信事業において当初計画では想定していなかったハイパースケーラーからの光コンポーネント製品のプロジェクト受注、売価アップがあり...",
    "direct_factors": [
      "ハイパースケーラーからの光コンポーネント製品プロジェクト受注（想定外）",
      "光コンポーネント製品の売価アップ",
      "水素不足影響の緩和"
    ],
    "structural_vulnerability": [
      "情報通信事業（光ファイバ・光コンポーネント）への売上集中度が高い",
      "水素関連製造プロセスへの依存により原材料不足リスクを内包"
    ],
    "spillover_conditions": [
      "光ファイバ・光コンポーネント製品を製造する電線・ケーブルメーカー",
      "ハイパースケーラー向けデータセンター関連製品を供給するメーカー",
      "水素利用製造プロセスを持つ素材・化学メーカー"
    ]
  }
}
```

### metric_name 正規化体系

PostgreSQLの既存テーブル（ProfitAndLoss・StockDividend）のカラム名に準拠。

| metric_name | 対応する原文例 | 準拠テーブル |
|---|---|---|
| `sales` | 売上高 / 売上収益 / 営業収益 | ProfitAndLoss.sales |
| `bussiness_income` | 営業利益 | ProfitAndLoss.bussiness_income ※typo踏襲 |
| `ordinary_income` | 経常利益（J-GAAPのみ） | ProfitAndLoss.ordinary_income |
| `net_income` | 当期純利益 / 親会社株主に帰属する当期純利益 | ProfitAndLoss.net_income |
| `ebitda` | EBITDA | —（対応カラムなし。公表指標として採用） |
| `eps` | 1株当たり当期（中間）純利益 | ProfitAndLoss.EPS |
| `dividend_per_share` | 1株当たり配当 | StockDividend.dividend_per_share |

---

## 9. 精度検証フロー

- Step1: デンソー3件・北川精機・フジクラ（計5件）でプロンプト動作確認
- Step2: 業種横断20件で spillover_conditions の質を人手評価
- Step3: OKなら既存4,353件の全件バッチ処理（初回のみ手動実行・約70分）
- Step4: 以降は日次差分処理（数件〜数十件・数分で完了）

---

## 10. バッチスケジュール（全体）

変更箇所を含む全スケジュール。

| No | バッチ名 | 変更後タイミング | 変更前 | 備考 |
|---|---|---|---|---|
| 120 | `run_tdnet.bat` | **17:30** | 20:00 | 前倒し |
| 110 | `run_taisyaku.bat` | **18:00** | 20:30 | 前倒し |
| 140 | `run_annual_accounts.bat` | 19:00 | 変更なし | irbank制限のため現状維持 |
| 500 | `post_buyback_data.bat` | **18:30** | 21:00 | tdnet依存のため前倒し |
| 510 | `run_midterm_plan_analysis.bat` | **18:45** | 20:45 | 前倒し |
| 520 | `daily_update.bat` | **19:00** | 21:45 | 前倒し |
| 530 | `run_forecast_revision.bat` | **19:15** | 新規 | PDF取得+LLM抽出+SQLite保存 |
| 540 | `post_forecast_revision.bat` | **19:45** | 新規 | 別システム実装済み |
| 150 | `run_quarterly_accounts_bulk.bat` | 21:30 | 変更なし | irbank制限のため現状維持 |
