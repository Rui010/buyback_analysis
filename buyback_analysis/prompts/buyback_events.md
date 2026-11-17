あなたはTDnetの自己株式関連開示から、独立したイベントを漏れなく抽出します。
出力形式はresponseSchemaで固定されています。

銘柄コード: {code}
会社名: {name}
開示タイトル: {title}

本文:
{content}

規則:
- 文書全体を1種類に分類せず、本文に含まれるイベントをevents配列へ個別に出す。
- 旧案件の完了と新しい取得枠の設定が同居する場合は、completionとnew_planを別イベントにする。
- 同じ旧案件について取得状況と取得終了を同時に報告している場合はcompletionだけを出し、同じ数値・期間からprogressを重複して作らない。
- 本文が「別文書で開示予定」「別途お知らせする」と述べるだけの買付けは、この文書自身のイベントではないためexecution_noticeを作らない。参照先の題名や予定額だけからイベントを増やさない。
- ToSTNeT-3等の買付予定・価格決定・買付結果を主題とする文書が、既存の取得決議と取得枠を再掲していてもexecution_noticeだけを出し、new_planを重複して作らない。
- 補足説明資料が既存決議・取得枠・買付方法を説明しているだけならsupplementだけを出す。補足資料自体で新たな決議又は買付予定・結果を公表していない限り、補足資料からexecution_noticeを作らない。既存決議日が本文にあればsupplementのresolution_dateへ入れる。
- source_quoteには判定根拠となる本文の原文を改変せず10文字以上で引用する。本文にない文を作らない。
- resolution_dateはイベントの根拠となる取得決議日とする。amendmentでは変更元の取得決議日を入れ、変更決議日はevent_dateへ入れる。
- referenced_document_dateは本文が参照する別文書の開示日であり、決議日を入れない。
- 不明な値は推測せずnullにする。confidenceは出力しない。
- company_own_transaction、independent_resolution、uses_existing_buyback_plan、related_to_buyback_planは、本文で確認できる場合だけtrue又はfalseとし、不明ならnullにする。
- 開示会社自身が自己株式を取得すると明記しているnew_planはcompany_own_transaction=trueにする。
- 取締役会等がその文書で新しい取得枠を決議したと明記しているnew_planはindependent_resolution=trueにする。過去決議の再掲や補足だけならtrueにしない。
- correction文書はPhase 1では抽出対象外なのでeventsを空配列にする。

値の形式:
- 日付は西暦のYYYY-MM-DDにする。年月や年しか分からない場合は日・月を補わずnullにする。
- 株数は株単位の整数にする。「万株」は10,000倍、「千株」は1,000倍する。
- 金額は円単位の整数にする。「億円」は100,000,000倍、「百万円」は1,000,000倍、「千円」は1,000倍する。
- 例: 5,000億円は500000000000、60,000百万円は60000000000、200万株は2000000。
- 比率や1株当たり価格を、取得株数・取得総額へ入れない。
- 取得株数又は取得総額が本文で0と明示されている場合、明示された0はnullにせず0として対応するcompletion又はprogressの項目へ入れる。
- completionでは、本文の取得実績表にある累計・合計の取得株数をshares_acquired、取得総額をamount_spent_yenへ入れる。「取得終了」の文章と実績表が離れていても同じ案件の最終値として扱う。

event_typeの定義:
- new_plan: 取締役会等が新しい自己株式取得枠を決議したイベント。既存決議の再掲や補足資料は含めない。
- amendment: 既存の取得枠、期間又は方法を変更したイベント。
- execution_notice: ToSTNeT-3等の買付予定、価格決定又は当該買付結果。取得枠全体の進捗・終了とは区別する。
- progress: 既存案件について、ある期間又は累計の取得実績を報告するイベント。
- completion: 取得期間の終了、取得枠の終了又は案件全体の完了を報告するイベント。一部のToSTNeT買付結果だけならexecution_noticeとする。
- supplement: 既存開示への補足説明であり、新しい決議・変更・実績を含まないイベント。
- equity_compensation: 株式報酬、譲渡制限付株式等に関連する自己株式取引。
- retirement: 自己株式の消却を決定又は実施したイベント。
- other_party_transaction: 親会社、子会社その他の別法人が主体で、当該上場会社自身の取得案件ではないイベント。
- other: 上記に該当しないイベント。訂正文書の代替分類には使わない。

payloadにはevent_typeに対応する項目だけを入れる。execution_noticeのsubtypeは、買付予定ならplanned、
価格決定ならprice_determined、買付結果ならresultとする。
