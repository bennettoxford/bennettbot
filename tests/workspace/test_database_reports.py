import json

import pytest

from bennettbot.job_configs import raw_config
from workspace.rotas import database_reports
from workspace.utils.people import Person
from workspace.utils.rota import NWeeklyCadence


DUMMY_A = Person("dummy-a", "UDUMMYA0001", "Dummy A")
DUMMY_B = Person("dummy-b", "UDUMMYB0001", "Dummy B")
DUMMY_C = Person("dummy-c", "UDUMMYC0001", "Dummy C")
TEAM_MEMBERS = [DUMMY_A, DUMMY_B, DUMMY_C]


@pytest.fixture
def patch_jobs(monkeypatch, tmp_path):
    monkeypatch.setattr(
        database_reports, "team_members", lambda team_name: TEAM_MEMBERS
    )
    monkeypatch.setattr(
        database_reports.DatabaseReportsReporter,
        "_state_path",
        lambda self: tmp_path / "team-rap-database-reports.json",
    )


def test_report_shows_only_who_is_currently_on_duty(freezer, patch_jobs):
    # The header/notes block shapes are generic RotaReporter behaviour,
    # covered elsewhere (test_rota.py) - here we're only checking the
    # section texts specific to DatabaseReportsReporter.report(): just the
    # current duty (not this/next), and NOTES appended after it.
    freezer.move_to("2024-01-01")  # before START_DATE

    blocks = json.loads(database_reports.report_rota())
    texts = [block["text"]["text"] for block in blocks if block["type"] == "section"]

    assert texts == [
        f"{DUMMY_A.formatted_slack_username} is on duty (05 Nov-02 Dec)",
        database_reports.NOTES,
    ]


@pytest.mark.parametrize(
    "advance_command",
    [database_reports.ADVANCE_COMMAND, None],
)
def test_report_advance_footnote(freezer, patch_jobs, advance_command):
    freezer.move_to("2024-01-01")
    reporter = database_reports._build_reporter()
    reporter.advance_command = advance_command

    blocks = json.loads(reporter.report())

    actions_blocks = [block for block in blocks if block["type"] == "actions"]
    if advance_command is None:
        assert not actions_blocks
    else:
        assert actions_blocks[-1]["elements"][0]["value"] == advance_command
        assert advance_command in {
            slack_command["command"]
            for namespace in raw_config.values()
            for slack_command in namespace["slack"]
        }


@pytest.mark.parametrize(
    "command,function",
    [
        ("rota", database_reports.report_rota),
        ("advance", database_reports.advance_rota),
        ("now", database_reports.now_rota),
    ],
)
def test_command_line_parser_dispatch(command, function):
    args = database_reports.get_command_line_parser().parse_args([command])

    assert args.function is function


def test_now_rota_names_who_is_on_database_reports_duty(freezer, patch_jobs):
    freezer.move_to("2024-01-01")

    assert (
        database_reports.now_rota()
        == f"{DUMMY_A.human_readable} is on database-reports duty."
    )


def test_advance_rota_shifts_the_rota_forward_by_one(freezer, patch_jobs):
    freezer.move_to("2024-01-01")

    message = database_reports.advance_rota()

    assert DUMMY_B.formatted_slack_username in message
    assert "database-reports duty" in message
    assert (
        database_reports.now_rota()
        == f"{DUMMY_B.human_readable} is on database-reports duty."
    )


def test_reporter_uses_a_four_weekly_cadence_from_the_start_date(monkeypatch):
    monkeypatch.setattr(
        database_reports, "team_members", lambda team_name: TEAM_MEMBERS
    )

    reporter = database_reports._build_reporter()

    assert isinstance(reporter.cadence, NWeeklyCadence)
    assert reporter.cadence.weeks == 4
    assert reporter.cadence.start_date == database_reports.START_DATE
