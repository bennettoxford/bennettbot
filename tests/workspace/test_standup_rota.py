import json
from datetime import datetime

import pytest

from workspace.standup import jobs
from workspace.standup.jobs import (
    daily_rota,
    get_command_line_parser,
    get_next_rota_date,
    weekly_rota,
)
from workspace.standup.jobs import get_pairs as real_get_pairs
from workspace.utils.people import Person


# Dummy people, not the real standup rota - the rota logic doesn't care who's
# in the pairs, just that it can pick a primary/secondary for each day.
PERSON_A = Person("person-a", "UPERSONA001", "Person A")
PERSON_B = Person("person-b", "UPERSONB001", "Person B")
PERSON_C = Person("person-c", "UPERSONC001", "Person C")
PERSON_D = Person("person-d", "UPERSOND001", "Person D")
PERSON_E = Person("person-e", "UPERSONE001", "Person E")
PERSON_F = Person("person-f", "UPERSONF001", "Person F")

DUMMY_PAIRS = {
    "monday": [PERSON_A, PERSON_B],
    "wednesday": [PERSON_C, PERSON_D],
    "friday": [PERSON_E, PERSON_F],
}


@pytest.fixture(autouse=True)
def dummy_pairs(monkeypatch):
    monkeypatch.setattr(jobs, "get_pairs", lambda: DUMMY_PAIRS)


def test_get_pairs_builds_three_consecutive_pairs(monkeypatch):
    # Skip the autouse dummy_pairs fixture and use real_get_pairs
    # (imported directly, above) to test the exactly-6 assertion
    monkeypatch.setattr(
        jobs,
        "team_members",
        lambda team_name: [PERSON_A, PERSON_B, PERSON_C, PERSON_D, PERSON_E, PERSON_F],
    )
    assert real_get_pairs() == DUMMY_PAIRS


@pytest.mark.parametrize("team_size", [5, 7])
def test_get_pairs_asserts_team_has_exactly_six_members(monkeypatch, team_size):
    monkeypatch.setattr(jobs, "team_members", lambda team_name: [PERSON_A] * team_size)

    with pytest.raises(AssertionError, match="exactly 6 members"):
        real_get_pairs()


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
                "text": "Monday: Person B (backup: Person A)\nWednesday: Person D (backup: Person C)\nFriday: Person F (backup: Person E)",
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
                "text": "Monday: Person A (backup: Person B)\nWednesday: Person C (backup: Person D)\nFriday: Person E (backup: Person F)",
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
                "text": "Monday: <@UPERSONB001> (backup: Person A)",
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
                "text": "Wednesday: <@UPERSONC001> (backup: Person D)",
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
