# 業績予想修正: 終了時ログとuploadエラー

## 変更

- 処理サマリーをfinallyに移し、SystemExit・通常例外・KeyboardInterruptでも途中集計を出してセッションを閉じる。OSによるプロセス強制停止では出力を保証できない。
- 成功通知は正常終了時のみ。保存件数はfailedを除外し、failed状態の保存件数を別表示する（PDF取得失敗時を含む）。
- check_missing_fieldsは既存のbool戻り値と個別[MISSING]ログを維持し、任意のdetailsリストへ同じ内訳を追加する。mainはfinallyでその内容を再掲する。欠損件数は項目数ではなく開示レコード数。
- google-genai 1.14.0のuploadはHTTPエラー検証前にfileキーを参照する経路がある。Stage1ネイティブPDF用クライアントに公開http_options.client_args経由でHTTPX response hookを設定し、400以上をAPIErrorに変換する。
- SDK本体や共用クライアントは変更しない。429はHTTP番号・銘柄コード・APIの理由をログに残して停止する。502/503/504の既存リトライは維持する。
- failedの再試行については[再試行設計](forecast_revision_failed_retry.md)を参照。

## 検証

- 新規テストの失敗を確認してから実装。
- HTTPX MockTransportで実SDKのupload経路に429/503を返し、fileキー参照前のAPIErrorを検証。単体テストでAPIへの実通信は行わない。
- mainはリポジトリ方針に従い全パイプラインの統合テストを追加せず、ASTで関数だけ取り出して初期化時にSystemExit・Exception・KeyboardInterruptを注入。サマリー1回、session.close 1回、成功通知なし、元例外の伝播を検証。
- 再試行対応を含め151テスト成功。native Stage1のカバレッジ99%、post_forecast_revisionは100%。
