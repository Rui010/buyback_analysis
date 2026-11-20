from unittest.mock import MagicMock

import pandas as pd

import buyback_analysis.main as main_module
import buyback_analysis.usecase.buyback_result_writer as writer_module


def test_integrity_conflict_is_not_counted_as_saved_and_notifies(monkeypatch):
    """保存されなかったURLにはsavedを付けず、エラー通知へ集計する。"""
    session = MagicMock()
    dataframe = pd.DataFrame(
        [
            {
                "code": "1803",
                "date": pd.Timestamp("2026-09-24"),
                "link": "https://example.test/140120260924539668.pdf",
                "title": "ToSTNeT-3による自己株式の買付け",
                "name": "清水建設",
            }
        ]
    )
    update_parse_status = MagicMock()
    notify_error = MagicMock()

    monkeypatch.setattr(main_module, "RERUN_URLS", [])
    monkeypatch.setattr(main_module, "SessionLocal", MagicMock(return_value=session))
    monkeypatch.setattr(main_module, "init_db", MagicMock())
    monkeypatch.setattr(main_module, "get_database_engine", MagicMock())
    monkeypatch.setattr(main_module, "get_tdnet_buyback_data", MagicMock(return_value=dataframe))
    monkeypatch.setattr(
        main_module, "get_detect_type_in_db", MagicMock(return_value="buyback_announcement")
    )
    monkeypatch.setattr(main_module, "data_exists_in_ir_tables", MagicMock(return_value=False))
    monkeypatch.setattr(main_module, "get_pdf_data", MagicMock(return_value="PDF本文"))
    monkeypatch.setattr(
        main_module,
        "parse_text_by_llm",
        MagicMock(return_value={"data": {"code": "1803", "buyback_shares": 1, "buyback_amount_yen": 1}}),
    )
    # 保存とparse_statusの更新はBuybackResultWriter経由で呼ばれる
    monkeypatch.setattr(writer_module, "post_data", MagicMock(return_value=False))
    monkeypatch.setattr(writer_module, "update_parse_status", update_parse_status)
    monkeypatch.setattr(main_module, "update_parse_status", update_parse_status)
    monkeypatch.setattr(main_module, "notify_error", notify_error)
    monkeypatch.setattr(main_module, "notify_success", MagicMock())

    main_module.main()

    update_parse_status.assert_called_once_with(
        session, "https://example.test/140120260924539668.pdf", "failed"
    )
    assert "制約違反:1件" in notify_error.call_args.args[1]
    assert "一意制約違反" not in notify_error.call_args.args[1]


def _setup_event_only_document(monkeypatch, parse_status, detect_type):
    """イベント結果は採用済みだが、従来テーブルに書く行がなかった文書を用意する。"""
    session = MagicMock()
    dataframe = pd.DataFrame(
        [
            {
                "code": "9246",
                "date": pd.Timestamp("2026-11-19"),
                "time": "15:30:00",
                "link": "https://example.test/140120261119583382.pdf",
                "title": "株式給付信託（BBT）の終了に関するお知らせ及び自己株式の消却方針に関するお知らせ",
                "name": "プロジェクトホールディングス",
            }
        ]
    )
    mocks = {
        "parse_text_by_llm": MagicMock(return_value=None),
        "detect_type_by_llm": MagicMock(return_value="retirement"),
        "get_pdf_data": MagicMock(return_value="PDF本文"),
        "get_pdf_path": MagicMock(return_value=None),
        "notify_error": MagicMock(),
        "notify_success": MagicMock(),
    }
    monkeypatch.setattr(main_module, "RERUN_URLS", [])
    monkeypatch.setattr(main_module, "SINGLE_LLM_ENABLED", True)
    monkeypatch.setattr(main_module, "SessionLocal", MagicMock(return_value=session))
    monkeypatch.setattr(main_module, "init_db", MagicMock())
    monkeypatch.setattr(main_module.ProvenanceRecorder, "from_env", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(main_module, "get_database_engine", MagicMock())
    monkeypatch.setattr(main_module, "get_tdnet_buyback_data", MagicMock(return_value=dataframe))
    monkeypatch.setattr(main_module, "has_buyback_event_result", MagicMock(return_value=True))
    monkeypatch.setattr(main_module, "get_detect_type_in_db", MagicMock(return_value=detect_type))
    monkeypatch.setattr(main_module, "get_parse_status_in_db", MagicMock(return_value=parse_status))
    monkeypatch.setattr(main_module, "data_exists_in_ir_tables", MagicMock(return_value=False))
    monkeypatch.setattr(main_module, "update_parse_status", MagicMock())
    monkeypatch.setattr(writer_module, "update_parse_status", MagicMock())
    for name, mock in mocks.items():
        monkeypatch.setattr(main_module, name, mock)
    return mocks


def test_event_only_document_is_not_sent_to_legacy_llm_again(monkeypatch):
    """互換保存で従来行がなかった（skipped）文書は、翌日以降も従来LLMへ回さない。"""
    mocks = _setup_event_only_document(monkeypatch, parse_status="skipped", detect_type="retirement")

    main_module.main()

    mocks["parse_text_by_llm"].assert_not_called()
    mocks["detect_type_by_llm"].assert_not_called()
    mocks["get_pdf_data"].assert_not_called()
    mocks["notify_error"].assert_not_called()
    assert "重複スキップ:1件" in mocks["notify_success"].call_args.args[1]


def test_failed_document_with_events_is_still_retried_by_legacy_llm(monkeypatch):
    """互換保存・従来LLMがともに失敗した文書（failed）は、従来どおり再試行する。"""
    mocks = _setup_event_only_document(monkeypatch, parse_status="failed", detect_type=None)

    main_module.main()

    mocks["parse_text_by_llm"].assert_called_once()
