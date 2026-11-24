from pathlib import Path


PROMPT = Path("buyback_analysis/prompts/buyback_events.md")


def test_prompt_prevents_duplicate_or_referenced_events():
    text = PROMPT.read_text(encoding="utf-8")

    assert "completionだけ" in text
    assert "別文書で開示予定" in text
    assert "execution_noticeを作らない" in text


def test_prompt_defines_new_plan_evidence_flags_and_zero_values():
    text = PROMPT.read_text(encoding="utf-8")

    assert "company_own_transaction=true" in text
    assert "independent_resolution=true" in text
    assert "明示された0はnullにせず0" in text
    assert "累計・合計の取得株数をshares_acquired" in text


def test_prompt_keeps_execution_and_supplement_documents_in_their_roles():
    text = PROMPT.read_text(encoding="utf-8")

    assert "new_planを重複して作らない" in text
    assert "supplementだけを出す" in text
    assert "補足資料からexecution_noticeを作らない" in text


def test_prompt_extracts_progress_cumulative_from_reference_section():
    text = PROMPT.read_text(encoding="utf-8")

    # 1文書・1案件のprogressを前文・当期実績・累計に分割しない
    assert "progressは1件だけ" in text
    # 累計は（ご参考）の「上記取締役会決議に基づき取得した自己株式の累計」から取る
    assert "（ご参考）" in text
    assert "自己株式の累計" in text
    # 当期（取得期間）の実績は累計ではない
    assert "当期の取得株数・取得総額をcumulative_" in text
    # 数値イベントの引用は前文ではなく数値の記載箇所
    assert "前文だけを引用しない" in text


def test_prompt_puts_cumulative_into_completion_for_status_and_end_reports():
    text = PROMPT.read_text(encoding="utf-8")

    assert "取得状況及び取得終了" in text
    assert "累計をcompletionのshares_acquired" in text


def test_prompt_normalizes_full_width_and_spaced_digits():
    text = PROMPT.read_text(encoding="utf-8")

    assert "全角数字" in text
    assert "860300" in text
    assert "270400" in text


def test_prompt_keeps_monthly_market_purchase_reports_out_of_execution_notice():
    text = PROMPT.read_text(encoding="utf-8")

    assert "市場買付の取得状況報告はprogressであり" in text


def _prompt_payload_fields(text: str) -> dict[str, set[str]]:
    section = text.split("payloadに入れてよい項目:", 1)[1].split("\n\n", 1)[0]
    fields = {}
    for line in section.strip().splitlines():
        event_type, names = line.removeprefix("- ").split(": ", 1)
        fields[event_type] = {name.strip() for name in names.split(",")}
    return fields


def test_prompt_lists_payload_fields_per_event_type_matching_strict_schemas():
    from buyback_analysis.usecase import event_schemas as s

    expected = {
        "new_plan": s.NewPlanPayload,
        "amendment": s.AmendmentPayload,
        "execution_notice": s.ExecutionNoticePayload,
        "progress": s.ProgressPayload,
        "completion": s.CompletionPayload,
        "supplement": s.SupplementPayload,
        "equity_compensation": s.EquityCompensationPayload,
        "retirement": s.RetirementPayload,
        "other_party_transaction": s.OtherPartyTransactionPayload,
        "other": s.OtherPayload,
    }
    listed = _prompt_payload_fields(PROMPT.read_text(encoding="utf-8"))

    assert set(listed) == set(expected)
    for event_type, payload_class in expected.items():
        assert listed[event_type] == set(payload_class.model_fields), event_type


def test_prompt_forbids_completion_fields_in_progress_and_joined_quotes():
    text = PROMPT.read_text(encoding="utf-8")

    assert "progressにshares_acquired・amount_spent_yenを入れない" in text
    assert "離れた箇所をつなげない" in text


def test_prompt_keeps_quotes_verbatim_and_values_uncomputed():
    text = PROMPT.read_text(encoding="utf-8")

    # 「の」を「的」に変える書き換えで引用照合に失敗していた。悪い例をプロンプトに書くと
    # 逆にその表記を誘発したため、例は書かず、数値の行を引用させる
    assert "1文字も変えずに写す" in text
    assert "自己株式的累計" not in text
    assert "（１）取得した株式の総数" in text
    # 当期と累計を足して本文にない累計を作っていた
    assert "足し合わせない" in text
    # 取得終了も報告する文書でprogressを重複させていた
    assert "累計をcompletionにだけ入れ、progressを出さない" in text
