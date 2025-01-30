import json
from datetime import datetime

from workspace.standup.jobs import (
    daily_rota,
    get_command_line_parser,
    get_next_rota_date,
    weekly_rota,
)


def test_weekly_rota_odd_week(freezer):
    freezer.move_to("2024-12-05")
    args = get_command_line_parser().parse_args(["weekly"])

    assert json.loads(weekly_rota(args)) == [
        {
            "text": {"text": "Team Rex stand ups this week", "type": "plain_text"},
            "type": "header",
        },
        {
            "text": {
                "text": "Monday: Jon (backup: Mike)\nWednesday: Steve (backup: Mary)\nFriday: Katie (backup: Thomas)",
                "type": "mrkdwn",
            },
            "type": "section",
        },
    ]


def test_weekly_rota_even_week(freezer):
    freezer.move_to("2024-12-09")
    args = get_command_line_parser().parse_args(["weekly"])

    assert json.loads(weekly_rota(args)) == [
        {
            "text": {"text": "Team Rex stand ups this week", "type": "plain_text"},
            "type": "header",
        },
        {
            "text": {
                "text": "Monday: Mike (backup: Jon)\nWednesday: Mary (backup: Steve)\nFriday: Thomas (backup: Katie)",
                "type": "mrkdwn",
            },
            "type": "section",
        },
    ]


def test_daily_rota_odd_week(freezer):
    freezer.move_to("2024-12-16")
    args = get_command_line_parser().parse_args(["daily", "monday"])

    assert json.loads(daily_rota(args)) == [
        {
            "text": {"text": "Team Rex stand up", "type": "plain_text"},
            "type": "header",
        },
        {
            "text": {
                "text": "Monday: <@U023ZG5H24R> (backup: Mike)",
                "type": "mrkdwn",
            },
            "type": "section",
        },
    ]


def test_daily_rota_even_week(freezer):
    freezer.move_to("2024-12-09")
    args = get_command_line_parser().parse_args(["daily", "wednesday"])

    assert json.loads(daily_rota(args)) == [
        {
            "text": {"text": "Team Rex stand up", "type": "plain_text"},
            "type": "header",
        },
        {
            "text": {
                "text": "Wednesday: <@U07LKQ06Q8L> (backup: Steve)",
                "type": "mrkdwn",
            },
            "type": "section",
        },
    ]


def test_get_weekday_date(freezer):
    freezer.move_to("2024-12-10")  # Tuesday
    assert get_next_rota_date("monday") == datetime(2024, 12, 16).date()
    assert get_next_rota_date("wednesday") == datetime(2024, 12, 11).date()
    assert get_next_rota_date("friday") == datetime(2024, 12, 13).date()

    freezer.move_to("2024-12-12")  # Thursday
    assert get_next_rota_date("monday") == datetime(2024, 12, 16).date()
    assert get_next_rota_date("wednesday") == datetime(2024, 12, 18).date()
    assert get_next_rota_date("friday") == datetime(2024, 12, 13).date()

    freezer.move_to("2024-12-15")  # Sunday
    assert get_next_rota_date("monday") == datetime(2024, 12, 16).date()
    assert get_next_rota_date("wednesday") == datetime(2024, 12, 18).date()
    assert get_next_rota_date("friday") == datetime(2024, 12, 20).date()
