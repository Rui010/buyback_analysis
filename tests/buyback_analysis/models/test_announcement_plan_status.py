from sqlalchemy import inspect

from buyback_analysis.models.announcement_plan_status import AnnouncementPlanStatus


def test_table_name_and_primary_key():
    mapper = inspect(AnnouncementPlanStatus)

    assert AnnouncementPlanStatus.__tablename__ == "announcement_plan_status"
    assert [column.name for column in mapper.primary_key] == ["buyback_plan_id"]


def test_columns_match_the_downstream_contract():
    mapper = inspect(AnnouncementPlanStatus)
    columns = {column.name for column in mapper.columns}

    assert columns == {
        "buyback_plan_id",
        "announcement_url",
        "code",
        "plan_status",
        "current_shares",
        "current_amount_yen",
        "current_start_date",
        "current_end_date",
        "cumulative_shares_acquired",
        "cumulative_amount_spent_yen",
        "completion_shares_acquired",
        "completion_amount_spent_yen",
        "progress_rate_amount",
        "progress_rate_shares",
        "latest_progress_date",
        "aggregation_rule_version",
        "calculated_at",
    }


def test_required_columns_are_not_nullable():
    table = AnnouncementPlanStatus.__table__

    for name in (
        "announcement_url",
        "code",
        "plan_status",
        "aggregation_rule_version",
        "calculated_at",
    ):
        assert table.columns[name].nullable is False, name


def test_announcement_url_is_indexed_for_the_front_join():
    table = AnnouncementPlanStatus.__table__

    assert table.columns["announcement_url"].index is True


def test_has_no_foreign_keys_so_it_can_be_synced_alone():
    table = AnnouncementPlanStatus.__table__

    assert not table.foreign_keys
