# 自社株買い案件紐づけ・訂正設計 Phase 2

## 1. 位置づけ

[Phase 1](buyback_plan_event_linking_design.md)完了後に、確定済み紐づけの自動訂正と
correctionの値適用を扱う。Phase 1の実装範囲には含めない。

## 2. 対象

- `LINKED -> UNRESOLVED / AMBIGUOUS / LINKED（別案件）`
- correctionの対象イベント特定
- amendmentの訂正及びcorrectionの訂正
- 旧案件・新案件の集計再計算
- 判定・適用履歴の保持

## 3. correction対象の表現

案件リンク用decisionとは別に`buyback_event_correction_decisions`を追加する。

| 列 | 内容 |
|---|---|
| `correction_decision_id` | 判定ID |
| `correction_event_uid` | correctionイベント |
| `status` | 3状態 |
| `target_event_uid` / `target_version_id` | 訂正対象イベントと抽出版 |
| `candidates` | 候補、根拠不足、矛盾 |
| `rule_version` / `input_fingerprint` | 判定版と入力hash |
| `supersedes_decision_id` / `is_current` | 履歴 |

amendment訂正はamendmentを、correctionの訂正は先行correctionを`target_event_uid`で参照する。

## 4. 確定・適用

対象URL、文書名と開示日、決議日・種別、訂正前値と対象抽出版の一致の順で検証する。
成立対象一つは`LINKED`、候補一つでも根拠不足は`UNRESOLVED`、複数成立は`AMBIGUOUS`とする。

元イベントは更新しない。対象イベントから現行correction参照グラフを作り、開示日時と
明示順で適用する。循環はエラーとして適用しない。有効イベントを業務有効日順に並べて
projectionを再構築する。

## 5. 確定済みリンクの自動訂正

新しい根拠又は旧根拠を否定する矛盾を必須とし、scoreやconfidence差だけでは変更しない。
新decision、現行切替、旧案件再計算、新案件再計算、projection切替を一トランザクションで
行い、失敗時は旧decisionと旧projectionを維持する。

run開始snapshotを固定し、各イベントは1 runに1回、同じfingerprintとルール版は再実行しない。
projection変更は同じrunの再判定トリガーにしない。同一`rule_version`で3回連続して状態又は
リンク先が往復した場合は自動更新を停止して`UNRESOLVED`にする。この上限値`3`は判定設定に
含め、変更時は`rule_version`を更新する。通常運用の人手承認は要求しない。

## 6. 実装前テスト仕様

- 確定リンクが根拠喪失・競合追加・明示参照により各状態へ遷移する。
- correctionがnew_plan、amendment、progress、completionを訂正できる。
- correctionの訂正を適用できる。
- correction循環を集計へ反映しない。
- 再リンク時に旧案件から除去し、新案件へ追加する。
- 再計算失敗時に旧状態を維持する。
- 同じ入力で履歴を増やさず、状態往復が収束条件で停止する。

Phase 1の本番受入後、別途承認を得て実装する。
