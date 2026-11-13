import json
from datetime import date

import pytest

from bennettbot import settings
from workspace.utils.blocks import RUN_COMMAND_BUTTON_ACTION_ID
from workspace.utils.people import Person
from workspace.utils.rota import (
    MonthlyCadence,
    NWeeklyCadence,
    RollingRotaReporter,
    WeeklyCadence,
)


PERSON_A = Person("person-a", "UPERSONA001", "Person A")
PERSON_B = Person("person-b", "UPERSONB001", "Person B")
PERSON_C = Person("person-c", "UPERSONC001", "Person C")
CANDIDATES = [PERSON_A, PERSON_B, PERSON_C]


class DummyRollingRotaReporter(RollingRotaReporter):
    def get_rota_text_for_interval(self, rota, interval_start, this_or_next):
        checker = rota[interval_start]
        return f"{this_or_next} ({self.format_interval(interval_start)}): {checker.human_readable}"


def make_reporter(tmp_path, state_key="dummy-rota", cadence=None, advance_command=None):
    kwargs = {} if cadence is None else {"cadence": cadence}
    reporter = DummyRollingRotaReporter(
        title="Dummy rota",
        candidates=CANDIDATES,
        state_key=state_key,
        advance_command=advance_command,
        **kwargs,
    )
    reporter._state_path = lambda: tmp_path / f"{state_key}.json"
    return reporter


def test_state_path_defaults_to_writeable_dir():
    reporter = DummyRollingRotaReporter(
        title="Dummy rota", candidates=CANDIDATES, state_key="dummy-rota"
    )

    assert reporter._state_path() == (
        settings.WRITEABLE_DIR / "rota_state" / "dummy-rota.json"
    )


def test_get_rota_picks_candidate_based_on_calendar_week(tmp_path, freezer):
    freezer.move_to("2024-03-25")  # Monday, ISO week 13
    reporter = make_reporter(tmp_path)

    rota = reporter.get_rota()

    assert rota[date(2024, 3, 25)] == CANDIDATES[13 % len(CANDIDATES)]
    assert rota[date(2024, 4, 1)] == CANDIDATES[(13 + 1) % len(CANDIDATES)]


def test_get_rota_is_unaffected_by_which_day_of_the_week_it_is(tmp_path, freezer):
    freezer.move_to("2024-03-25")
    rota_on_monday = make_reporter(tmp_path).get_rota()

    freezer.move_to("2024-03-26")
    rota_on_tuesday = make_reporter(tmp_path).get_rota()

    assert rota_on_monday == rota_on_tuesday


def test_advance_shifts_the_rota_by_one_candidate(tmp_path, freezer):
    freezer.move_to("2024-03-25")  # Monday, ISO week 13
    reporter = make_reporter(tmp_path)
    before = reporter.get_rota()[date(2024, 3, 25)]

    message = reporter.advance()

    after = make_reporter(tmp_path).get_rota()[date(2024, 3, 25)]
    expected_index = (CANDIDATES.index(before) + 1) % len(CANDIDATES)
    assert after == CANDIDATES[expected_index]
    assert after.formatted_slack_username in message


def test_now_names_who_is_on_duty(tmp_path, freezer):
    freezer.move_to("2024-03-25")  # Monday, ISO week 13
    reporter = make_reporter(tmp_path)

    message = reporter.now()

    checker = reporter.get_rota()[date(2024, 3, 25)]
    assert message == f"{checker.human_readable} is on duty."


def test_now_names_the_duty_when_given(tmp_path, freezer):
    freezer.move_to("2024-03-25")  # Monday, ISO week 13
    reporter = make_reporter(tmp_path)

    message = reporter.now("update-dependencies")

    checker = reporter.get_rota()[date(2024, 3, 25)]
    assert message == f"{checker.human_readable} is on update-dependencies duty."


def test_advance_names_the_duty_when_given(tmp_path, freezer):
    freezer.move_to("2024-03-25")  # Monday, ISO week 13
    reporter = make_reporter(tmp_path)

    message = reporter.advance("update-dependencies")

    assert "is now on update-dependencies duty." in message


def test_advance_persists_across_new_reporter_instances(tmp_path, freezer):
    freezer.move_to("2024-03-25")
    make_reporter(tmp_path).advance()

    rota = make_reporter(tmp_path).get_rota()

    assert rota[date(2024, 3, 25)] == CANDIDATES[(13 + 1) % len(CANDIDATES)]


def test_state_is_isolated_per_state_key(tmp_path, freezer):
    freezer.move_to("2024-03-25")
    make_reporter(tmp_path, state_key="rota-one").advance()

    rota_one = make_reporter(tmp_path, state_key="rota-one").get_rota()
    rota_two = make_reporter(tmp_path, state_key="rota-two").get_rota()

    assert rota_one[date(2024, 3, 25)] != rota_two[date(2024, 3, 25)]


@pytest.mark.parametrize(
    "weekday,d,expected",
    [
        # Defaults to Monday-anchored.
        (None, date(2024, 3, 28), date(2024, 3, 25)),  # Thursday -> Monday
        # Anchored to Wednesday (weekday=2). The most recent Wednesday on or
        # before each of these dates is 2024-03-27.
        (2, date(2024, 3, 27), date(2024, 3, 27)),  # Wed itself
        (2, date(2024, 3, 28), date(2024, 3, 27)),  # Thu
        (2, date(2024, 4, 1), date(2024, 3, 27)),  # Mon
        (2, date(2024, 4, 3), date(2024, 4, 3)),  # next Wed
    ],
)
def test_weekly_cadence_interval_start(weekday, d, expected):
    cadence = WeeklyCadence() if weekday is None else WeeklyCadence(weekday=weekday)

    assert cadence.interval_start(d) == expected


@pytest.mark.parametrize(
    "advance_command,expected_action_block",
    [
        (None, None),
        (
            "some-namespace some-command",
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Not available? Advance the rota",
                        },
                        "action_id": RUN_COMMAND_BUTTON_ACTION_ID,
                        "value": "some-namespace some-command",
                    }
                ],
            },
        ),
    ],
)
def test_report_advance_footnote(
    tmp_path, freezer, advance_command, expected_action_block
):
    freezer.move_to("2024-03-25")
    reporter = make_reporter(tmp_path, advance_command=advance_command)

    blocks = json.loads(reporter.report())

    if expected_action_block is None:
        assert not any(block["type"] == "actions" for block in blocks)
    else:
        assert blocks[-1] == expected_action_block


def test_report_includes_rota_text_for_this_and_next(tmp_path, freezer):
    freezer.move_to("2024-03-25")
    reporter = make_reporter(tmp_path)

    blocks = json.loads(reporter.report())

    texts = [block["text"]["text"] for block in blocks if block["type"] == "section"]
    assert texts == [
        "this (25 Mar-29 Mar): Person B",
        "next (01 Apr-05 Apr): Person C",
    ]


def test_get_rota_and_advance_use_the_cadence_for_all_date_math(tmp_path, freezer):
    # 2024-03-25 and 2024-04-01 are both within the same fortnight (interval
    # 1: 2024-03-25 to 2024-04-07), so a weekly-hardcoded implementation
    # would wrongly treat them as two different intervals, and so pick two
    # different "now" candidates.
    cadence = NWeeklyCadence(weeks=2, start_date=date(2024, 3, 11))  # a Monday

    freezer.move_to("2024-03-25")
    rota_at_start_of_fortnight = make_reporter(tmp_path, cadence=cadence).get_rota()

    freezer.move_to("2024-04-01")
    rota_a_week_later = make_reporter(tmp_path, cadence=cadence).get_rota()

    assert rota_at_start_of_fortnight == {
        date(2024, 3, 25): CANDIDATES[1 % len(CANDIDATES)],
        date(2024, 4, 8): CANDIDATES[2 % len(CANDIDATES)],
    }
    assert rota_a_week_later == rota_at_start_of_fortnight

    freezer.move_to("2024-03-25")
    message = make_reporter(tmp_path, cadence=cadence).advance()
    assert CANDIDATES[(1 + 1) % len(CANDIDATES)].formatted_slack_username in message


@pytest.mark.parametrize(
    "d,expected",
    [
        # Any day within the same 4-week block maps to the same interval
        # start, which falls on the same weekday as start_date (a Thursday).
        (date(2024, 1, 4), date(2024, 1, 4)),  # start_date itself
        (date(2024, 1, 8), date(2024, 1, 4)),
        (date(2024, 1, 31), date(2024, 1, 4)),
        (date(2024, 2, 1), date(2024, 2, 1)),  # the next block
        # Before start_date (e.g. trying out the rota ahead of going live)
        # still reports the first interval, rather than counting backwards
        # into a notional earlier cycle.
        (date(2024, 1, 3), date(2024, 1, 4)),
        (date(2023, 12, 1), date(2024, 1, 4)),
    ],
)
def test_n_weekly_cadence_interval_start(d, expected):
    cadence = NWeeklyCadence(weeks=4, start_date=date(2024, 1, 4))

    assert cadence.interval_start(d) == expected


@pytest.mark.parametrize(
    "weeks,expected", [(4, date(2024, 1, 12)), (6, date(2024, 1, 26))]
)
def test_n_weekly_cadence_next_interval_start_and_index_advance_by_one_block(
    weeks, expected
):
    cadence = NWeeklyCadence(weeks=weeks, start_date=date(2023, 12, 15))

    assert cadence.next_interval_start(date(2023, 12, 15)) == expected
    assert (
        cadence.interval_index(expected)
        == cadence.interval_index(date(2023, 12, 15)) + 1
    )


@pytest.mark.parametrize(
    "day_of_month,d,expected",
    [
        (None, date(2024, 3, 17), date(2024, 3, 1)),  # defaults to the 1st
        (15, date(2024, 3, 15), date(2024, 3, 15)),  # on day_of_month
        (15, date(2024, 3, 20), date(2024, 3, 15)),  # after day_of_month
        # Before day_of_month belongs to the interval that started last
        # month - not a one-off "before the rota's first interval" case
        # like NWeeklyCadence's start_date, since day_of_month recurs every
        # month.
        (15, date(2024, 3, 14), date(2024, 2, 15)),
        (15, date(2024, 1, 1), date(2023, 12, 15)),  # rolls back over a year
    ],
)
def test_monthly_cadence_interval_start(day_of_month, d, expected):
    cadence = (
        MonthlyCadence()
        if day_of_month is None
        else MonthlyCadence(day_of_month=day_of_month)
    )

    assert cadence.interval_start(d) == expected


@pytest.mark.parametrize("day_of_month", [0, 29])
def test_monthly_cadence_rejects_day_of_month_outside_1_to_28(day_of_month):
    with pytest.raises(ValueError):
        MonthlyCadence(day_of_month=day_of_month)


@pytest.mark.parametrize(
    "interval_start,expected",
    [
        (date(2024, 3, 15), date(2024, 4, 15)),
        (date(2024, 12, 15), date(2025, 1, 15)),  # rolls over the year
    ],
)
def test_monthly_cadence_next_interval_start(interval_start, expected):
    cadence = MonthlyCadence(day_of_month=15)

    assert cadence.next_interval_start(interval_start) == expected


def test_monthly_cadence_interval_index_is_consistent_across_a_year_boundary():
    # Unlike WeeklyCadence's ISO week number, which resets each year,
    # MonthlyCadence's index must keep incrementing by one across a
    # December-to-January rollover.
    cadence = MonthlyCadence(day_of_month=15)

    december = cadence.interval_index(date(2024, 12, 15))
    january = cadence.interval_index(date(2025, 1, 15))

    assert january == december + 1
