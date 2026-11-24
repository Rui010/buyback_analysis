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
- 1つの文書が1つの案件の取得状況を報告している場合、progressは1件だけ出す。前文、当期の取得実績、累計を別々のprogressに分けない。
- 市場買付の取得状況報告はprogressであり、ToSTNeT-3等の買付でない限りexecution_noticeを作らない。
- 数値を持つイベントのsource_quoteには、値が書かれた箇所を引用する。「下記のとおりお知らせいたします」等の前文だけを引用しない。progressと累計を使うcompletionでは、累計欄の見出しではなく「（１）取得した株式の総数」から取得価額の総額までの数値の行を引用する。
- source_quoteは本文の連続した1か所だけを引用する。離れた箇所をつなげない。「…」等で途中を省略しない。
- source_quoteは本文の文字を1文字も変えずに写す。助詞や記号も本文のとおりにする。
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
- 全角数字は半角に直し、桁区切りや数字の間の空白は取り除く。例: ８６０,３００株は860300、2 7 0 , 4 0 0株は270400、０株は0。
- 比率や1株当たり価格を、取得株数・取得総額へ入れない。
- 取得株数又は取得総額が本文で0と明示されている場合、明示された0はnullにせず0として対応するcompletion又はprogressの項目へ入れる。
- completionでは、本文の取得実績表にある累計・合計の取得株数をshares_acquired、取得総額をamount_spent_yenへ入れる。「取得終了」の文章と実績表が離れていても同じ案件の最終値として扱う。
- 取得状況報告では、冒頭の「取得した株式の総数」「取得価額の総額」は取得期間（当期）の実績であり、案件全体の累計は（ご参考）欄の「上記取締役会決議に基づき取得した自己株式の累計（○年○月○日現在）」に書かれることが多い。（ご参考）欄は過去決議の再掲だけではなく、この文書が報告する累計を含む。
- progressでは、その累計の株数をcumulative_shares_acquired、金額をcumulative_amount_spent_yenへ入れ、取得期間をperiod_start・period_endへ入れる。当期の取得株数・取得総額をcumulative_shares_acquired・cumulative_amount_spent_yenへ入れない。累計の記載がなければnullにする。
- 本文に書かれていない値を計算で作らない。当期の実績と累計を足し合わせない。累計の基準日が取得期間の末日より前でも、本文の累計値をそのまま入れる。
- 取得状況と取得終了を同時に報告している文書では、累計をcompletionにだけ入れ、progressを出さない。
- 「取得状況及び取得終了」「取得状況および取得終了」の文書で（ご参考）欄に累計がある場合は、その累計をcompletionのshares_acquired・amount_spent_yenへ入れ、当期の実績を最終値にしない。累計欄がなく実績表が1つだけなら、その表の値を入れる。

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

payloadにはevent_typeに対応する項目だけを入れる。下の一覧にない項目は、値を入れても保存されずに捨てられる。
progressにshares_acquired・amount_spent_yenを入れない。progressの株数・金額はcumulative_shares_acquired・
cumulative_amount_spent_yenにだけ入れる。

payloadに入れてよい項目:
- new_plan: company_own_transaction, independent_resolution, buyback_shares, buyback_amount_yen, start_date, end_date, buyback_method, purpose, share_type
- amendment: previous_buyback_shares, changed_buyback_shares, previous_buyback_amount_yen, changed_buyback_amount_yen, previous_start_date, changed_start_date, previous_end_date, changed_end_date, previous_buyback_method, changed_buyback_method
- execution_notice: subtype, execution_date, planned_buyback_shares, planned_buyback_amount_yen, executed_shares, executed_amount_yen, price_per_share_yen, buyback_method
- progress: cumulative_shares_acquired, cumulative_amount_spent_yen, period_start, period_end
- completion: shares_acquired, amount_spent_yen, start_date, end_date, buyback_method
- supplement: description
- equity_compensation: uses_existing_buyback_plan, description, buyback_shares, buyback_amount_yen, start_date, end_date
- retirement: related_to_buyback_plan, retirement_shares, retirement_date, share_type
- other_party_transaction: other_party_code, other_party_name, transaction_role, description
- other: description

execution_noticeのsubtypeは、買付予定ならplanned、価格決定ならprice_determined、買付結果ならresultとする。
