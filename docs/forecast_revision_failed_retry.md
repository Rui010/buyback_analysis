# 業績予想修正: failedレコードの再試行

## 動作

- 通常実行は既存レコードのextraction_statusがfailedなら再抽出する。okの欠損項目は再処理しない。
- failedのURLを日付制限なしでTDnetから取り直し、通常の取得範囲とcode/linkで重複排除する。取得範囲を過ぎた失敗も取りこぼさない。
- API呼び出し前に既存failed行を削除しない。抽出完了後、保存処理の同一トランザクションでfailed行とその指標を置換する。失敗時はrollbackで元に戻す。okなどの既存行を上書きしない。
- 訂正文書もStage1が失敗した場合はcorrectionではなくfailedとして扱う。
- 429時はログにHTTPコードを出して停止し、既存failed行は次回再試行対象として残る。
- スキーマ変更なし。

## 検証

テストファーストで失敗を確認後、forecast_revision_analysisの151テストが成功。retry_failedとpost_forecast_revisionのカバレッジ100%、native Stage1は99%。mainを含むパッケージ全体72%（main全体の統合テストは既存方針により対象外）。

インメモリSQLiteで以下を検証する。

- failedから成功状態への置換
- 保存失敗時のrollbackと元のfailed記録の保持
- 成功済みレコードの保護
- 過去日付のfailedも再試行対象に含めること
