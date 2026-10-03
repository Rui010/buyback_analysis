from unittest.mock import MagicMock

import pandas as pd

import buyback_analysis.main as main_module


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
    monkeypatch.setattr(main_module, "post_data", MagicMock(return_value=False))
    monkeypatch.setattr(main_module, "update_parse_status", update_parse_status)
    monkeypatch.setattr(main_module, "notify_error", notify_error)
    monkeypatch.setattr(main_module, "notify_success", MagicMock())

    main_module.main()

    update_parse_status.assert_called_once_with(
        session, "https://example.test/140120260924539668.pdf", "failed"
    )
    assert "制約違反:1件" in notify_error.call_args.args[1]
    assert "一意制約違反" not in notify_error.call_args.args[1]
