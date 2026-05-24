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
