# デザインドック：訂正（correction）と元データの紐付け・修正適用

## 背景・問題

現状、`corrections` テーブルは `original_announcement_date`（元の発表日）と `code`（企業コード）を持っているが、**どのテーブルのどのレコードを訂正したか**が特定できない。

- 訂正対象は `announcements` / `progress` / `completion` の3テーブルいずれかのはずだが、どれか不明
- 元レコードに「訂正あり」というフラグも立てられていない
- 元レコードの値が訂正後の正しい値に更新されない
- 分析時に手動照合が必要

---

## ゴール

1. `corrections` レコードから、訂正対象の元レコードを一意に特定できる
2. 元レコード側に「訂正が存在する」ことをフラグとして記録する
3. 元レコードの値を訂正内容で自動上書きする
4. 既存の処理フロー（`main.py`）への影響を最小限に抑える

## ノンゴール

- 訂正の履歴管理・バージョン管理（訂正は常に元レコードへの上書きとするため、訂正の訂正も同じフローで自然に解決される）

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
  corrections (JSON)         ← [{section, before_text, after_text}, ...]

announcements
  status: no_correction / has_correction / corrected  ← 発表のみ存在
```

`progress`・`completion` には `status` カラムがない。

---

## corrections JSON の実データ構造

LLMが抽出した `corrections` フィールドは以下の形式。`section` は「不明」になるケースが多く、`before_text` / `after_text` はラベルと値が混在した生テキスト。

```json
[
  {
    "section": "３．株式の取得価額の総額",
    "before_text": "３．株式の取得価額の総額   101,323,864円",
    "after_text":  "３．株式の取得価額の総額   101,317,400円"
  },
  {
    "section": "不明",
    "before_text": "（５）取得方法   市場買付",
    "after_text":  "（５）取得方法   名古屋証券取引所の自己株式立会外買付取引（ToSTNeT-3）による買付け"
  }
]
```

`before_text == after_text` のエントリは実質変更なし。変更があるエントリのみ抽出対象。

---

## 提案する設計

### 処理を2ステップに分ける

| ステップ | 単位 | 手法 | 概要 |
|---|---|---|---|
| **① 紐付け** | 1日分バッチ | LLM | 訂正一覧と企業IRをまとめて渡し、どの元レコードに対応するかをLLMが判定 |
| **② 修正適用** | 1件ずつ | LLM | 元レコードの現在値と corrections[] を渡し、更新すべきフィールドのパッチをLLMが返す |

---

### 1. `corrections` テーブルにカラムを追加

| 追加カラム | 型 | 説明 |
|---|---|---|
| `linked_table` | String | 紐付け先テーブル名（`buyback_announcements` / `buyback_progress` / `buyback_completion`） |
| `linked_record_url` | String | 紐付け先レコードの URL（元レコードの主キー相当） |
| `linked` | Boolean | 紐付けが成功したか（デフォルト: False） |
| `applied` | Boolean | 修正値の適用が完了したか（デフォルト: False） |

---

### 2. `progress`・`completion` にも `status` カラムを追加

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

### 3. 新 usecase：`link_corrections_by_llm.py`（ステップ①）

日次バッチとして、当日取り込んだ訂正レコードをまとめて処理する。

**LLMへの入力：**
- 当日の訂正一覧（`corrections` テーブルの当日レコード：id / document_title / original_announcement_date / code）
- 各企業（code）のその日までの IR 一覧（announcements / progress / completion の url / disclosure_date / company_name を結合したリスト）

**LLMへの依頼内容：**
> 各訂正がどの元IRレコードに対応するか特定してください。`document_title` の文言と `original_announcement_date` を手がかりに、元IRの種別（テーブル名）と URL を返してください。

**LLMの出力イメージ：**
```json
[
  {
    "correction_id": 1,
    "linked_table": "buyback_completion",
    "linked_record_url": "https://...140120250318521453.pdf"
  },
  {
    "correction_id": 2,
    "linked_table": "buyback_progress",
    "linked_record_url": "https://...140120250507536300.pdf"
  }
]
```

**処理：**
- 紐付けできた → `corrections.linked_table` / `linked_record_url` / `linked = True` を更新
  、元レコードの `status → has_correction` を更新
- 紐付けできなかった → `linked = False` のままログ出力

**コンテキスト量の制御：**
- 企業ごとの IR は直近1年分に絞る（古すぎる訂正は稀なため）
- 1日の訂正件数が多い場合は企業単位でバッチを分割する

---

### 4. 新 usecase：`apply_correction_by_llm.py`（ステップ②）

`linked = True` かつ `applied = False` のレコードを1件ずつ処理する。

**LLMへの入力：**
- 元レコードの現在値（フィールド名: 値 の形式）
- `corrections[]` の `before_text` / `after_text`（`before_text == after_text` のエントリは除外して渡す）
- 更新可能なフィールド名の一覧（テーブルのカラム名）

**LLMへの依頼内容：**
> `after_text` の内容から、元レコードのどのフィールドをどの値に更新すべきかを JSON で返してください。変更がないフィールドは含めないでください。数値フィールドは数値型で返してください。

**LLMの出力イメージ：**
```json
{
  "cumulative_amount_spent_yen": 101317400
}
```

**処理：**
- ORM モデルに patch 適用
- 元レコードの `status → corrected` に更新
- `corrections.applied = True` に更新

---

### 5. `main.py` への組み込み

```python
# 既存処理（変更なし）
post_data(session, obj)

# 追加：全件処理後に当日分の紐付けを実行
link_corrections_by_llm(session, target_date=today)

# 追加：紐付け済み・未適用のレコードを修正適用
apply_corrections_by_llm(session)
```

---

## 処理フロー（変更後）

```
[PDF取得・種別判定・保存] ← 変更なし
        ↓
  全件ループ完了
        ↓
  link_corrections_by_llm()          ← ステップ①（1日分バッチ）
    ├─ 当日の訂正一覧を取得
    ├─ 各企業の直近IR一覧を取得
    ├─ LLMで訂正↔元レコードを対応付け
    ├─ corrections.linked_table / linked_record_url / linked 更新
    └─ 元レコードの status → has_correction
        ↓
  apply_corrections_by_llm()         ← ステップ②（1件ずつ）
    ├─ linked=True, applied=False のレコードを取得
    ├─ LLMで修正フィールドのパッチを生成
    ├─ 元レコードに patch 適用
    ├─ 元レコードの status → corrected
    └─ corrections.applied → True
```

---

## 既存データの移行方針

既に `corrections` テーブルに蓄積されているレコードは `linked` / `applied` が `null` の状態になる。

**移行スクリプト（別途作成）の方針：**
1. `corrections` の全レコードを取得
2. 開示日ごとにグループ化し、`link_corrections_by_llm()` と同じロジックで順次処理
3. 紐付けが完了したものから `apply_corrections_by_llm()` で修正適用

---

## 未解決の問題（実装前に確認したい点）

| 問題 | 内容 |
|---|---|
| **元レコードが存在しない場合** | 訂正が先に届いて元データがまだ取り込まれていないケース。`linked=False` のまま放置でよいか、定期的に再試行する仕組みが必要か |
| **1つの訂正が複数テーブルにまたがる場合** | 例：発表と完了の両方を訂正する1つのIR。現実に存在するか確認が必要 |
| **LLMが紐付けを誤る場合** | 同一企業の同日IR複数件があるケース（id=4,5 のデンキョーが該当）。LLMに渡す候補を絞り込む工夫が必要か |
| **ステップ②でパッチが空になる場合** | LLMがフィールドを特定できない場合の扱い。`applied=False` のまま残すかフラグを分けるか |
