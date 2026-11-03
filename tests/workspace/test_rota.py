import json
from datetime import date, timedelta

from bennettbot import settings
from workspace.utils.people import Person
from workspace.utils.rota import RollingRotaReporter


PERSON_A = Person("person-a", "UPERSONA001", "Person A")
PERSON_B = Person("person-b", "UPERSONB001", "Person B")
PERSON_C = Person("person-c", "UPERSONC001", "Person C")
CANDIDATES = [PERSON_A, PERSON_B, PERSON_C]


class DummyRollingRotaReporter(RollingRotaReporter):
    def get_rota_text_for_interval(self, rota, interval_start, this_or_next):
        checker = rota[interval_start]
        return f"{this_or_next} ({self.format_interval(interval_start)}): {checker.human_readable}"


class FakeFortnightlyCadence:
    """A non-weekly cadence, to prove RollingRotaReporter doesn't hardcode
    weekly math anywhere - intervals start every other Monday from a fixed
    anchor, two weeks apart."""

    anchor = date(2024, 3, 11)  # a Monday

    def interval_index(self, interval_start: date) -> int:
        return (interval_start - self.anchor).days // 14

    def interval_start(self, d: date) -> date:
        monday = d - timedelta(days=d.weekday())
        fortnights_since_anchor = (monday - self.anchor).days // 14
        return self.anchor + timedelta(weeks=2 * fortnights_since_anchor)

    def next_interval_start(self, interval_start: date) -> date:
        return interval_start + timedelta(weeks=2)


def make_reporter(tmp_path, state_key="dummy-rota", cadence=None):
    kwargs = {} if cadence is None else {"cadence": cadence}
    reporter = DummyRollingRotaReporter(
        title="Dummy rota", candidates=CANDIDATES, state_key=state_key, **kwargs
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
    assert after.human_readable in message


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
    cadence = FakeFortnightlyCadence()

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
    assert CANDIDATES[(1 + 1) % len(CANDIDATES)].human_readable in message
