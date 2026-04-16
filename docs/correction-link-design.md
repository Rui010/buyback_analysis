# デザインドック：訂正（correction）と元データの紐付け

## 背景・問題

現状、`corrections` テーブルは `original_announcement_date`（元の発表日）と `code`（企業コード）を持っているが、**どのテーブルのどのレコードを訂正したか**が特定できない。

- 訂正対象は `announcements` / `progress` / `completion` の3テーブルいずれかのはずだが、どれか不明
- 元レコードに「訂正あり」というフラグも立てられていない
- 分析時に手動照合が必要

---

## ゴール

1. `corrections` レコードから、訂正対象の元レコードを一意に特定できる
2. 元レコード側に「訂正が存在する」ことをフラグとして記録する
3. 既存の処理フロー（`main.py`）への影響を最小限に抑える

## ノンゴール

- 元レコードの値を訂正内容で自動上書きすること（どう上書きするかはビジネス判断が必要なため対象外）
- 複数世代の訂正の連鎖追跡（訂正の訂正など）

---

## 現状のデータモデル

```
corrections
  id                         (PK)
  code
  url
  company_name
  disclosure_date            ← 訂正IRの開示日
  original_announcement_date ← 元文書の発表日（どのテーブルか不明）
  document_title
  correction_reason
  corrections (JSON)

announcements
  status: no_correction / has_correction / corrected  ← 発表のみ存在
```

`progress`・`completion` には `status` カラムがない。

---

## 提案する設計

### 1. LLMが「元文書の種別」も抽出する

`correction.md` プロンプトに `original_document_type` フィールドを追加。

```
"original_document_type": "訂正対象の元文書の種類。
  以下から選択：
  - buyback_announcement（自己株式取得の発表）
  - buyback_progress（取得状況の途中報告）
  - buyback_completion（取得完了の報告）
  - unknown（判断できない場合）"
```

判定根拠は `document_title` フィールドの文言（例：「自己株式の取得状況に関するお知らせ」→ progress）。

---

### 2. `corrections` テーブルにカラムを追加

| 追加カラム | 型 | 説明 |
|---|---|---|
| `original_document_type` | String | LLMが判定した元文書の種別 |
| `linked` | Boolean | 元レコードへの紐付けが成功したか |

`original_announcement_date` は既に存在するため、`(code, original_announcement_date, original_document_type)` の3つで元レコードを検索できる。

---

### 3. `progress`・`completion` にも `status` カラムを追加

`announcement` と同様に `AnnouncementStatus` Enum を流用する。

```python
# models/progress.py, models/completion.py に追加
status = Column(
    Enum(AnnouncementStatus),
    nullable=True,
    default=AnnouncementStatus.no_correction,
)
```

---

### 4. 新 usecase：`link_correction.py`

`corrections` 保存後に呼び出す。

```
link_correction(session, correction_data)
  ↓
original_document_type を確認
  ↓
対応テーブルで (code, disclosure_date == original_announcement_date) を検索
  ↓
見つかった → 元レコードの status を has_correction に更新
             corrections.linked = True に更新
見つからない → corrections.linked = False のまま（ログ出力）
```

---

### 5. `main.py` の変更箇所

変更前：
```python
post_data(session, obj)
```

変更後：
```python
post_data(session, obj)

if detect_type_enum == DetectType.CORRECTION:
    link_correction(session, obj["data"])
```

---

## 処理フロー（変更後）

```
[PDF取得・種別判定] ← 変更なし
        ↓
  parse_text_by_llm()  ← correction.md に original_document_type を追加
        ↓
   post_data()         ← corrections テーブルに保存（linked=False で初期値）
        ↓
  [CORRECTIONの場合のみ]
        ↓
  link_correction()
    ├─ 元テーブルを検索
    ├─ 元レコードの status → has_correction
    └─ correction.linked → True
```

---

## 既存データの移行方針

既に `corrections` テーブルに蓄積されているレコードは `original_document_type` が `null` の状態になる。

**移行スクリプト（別途作成）の方針：**
1. `corrections` の全レコードを取得
2. `document_title` のキーワードで `original_document_type` を推定（ルールベース）
3. `link_correction()` ロジックで元レコードを検索・紐付け

---

## 未解決の問題（実装前に確認したい点）

| 問題 | 内容 |
|---|---|
| **元レコードが存在しない場合** | 訂正が先に届いて元データがまだ取り込まれていないケース。`linked=False` のまま放置でよいか、定期的に再試行する仕組みが必要か |
| **1つの訂正が複数テーブルにまたがる場合** | 例：発表と完了の両方を訂正する1つのIR。現実に存在するか確認が必要 |
| **`original_announcement_date` の精度** | LLMが元の日付を誤って抽出するケースで、元レコードが見つからない可能性。フォールバック（コードだけで絞り込んで候補を出す）が必要か |
