import json

from workspace.rotas import update_dependencies as jobs
from workspace.utils.people import Person


DUMMY_A = Person("dummy-a", "UDUMMYA0001", "Dummy A")
DUMMY_B = Person("dummy-b", "UDUMMYB0001", "Dummy B")
DUMMY_C = Person("dummy-c", "UDUMMYC0001", "Dummy C")
TEAM_MEMBERS = [DUMMY_A, DUMMY_B, DUMMY_C]

TEAM_NAME = "Team Dummy"
REPOS = ["org/repo-one", "org/repo-two"]

DUTY_TEXT = (
    "On duty this week (25 Mar-29 Mar): <@UDUMMYB0001>\n"
    "On duty next week (01 Apr-05 Apr): Dummy C"
)

ALL_OPEN_PRS_LINK_TEXT = (
    "<https://github.com/pulls?q=is%3Apr+is%3Aopen+"
    "%28repo%3Aorg%2Frepo-one+OR+repo%3Aorg%2Frepo-two%29+"
    "label%3Adependencies"
    "|All open PRs>"
)

REPO_FIELDS_BLOCK = {
    "type": "section",
    "fields": [
        {
            "type": "mrkdwn",
            "text": "• <https://github.com/org/repo-one/pulls|org/repo-one>",
        },
        {
            "type": "mrkdwn",
            "text": "• <https://github.com/org/repo-two/pulls|org/repo-two>",
        },
    ],
}


def patch_jobs(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "team_members", lambda team_name: TEAM_MEMBERS)
    monkeypatch.setattr(
        jobs.repos_config, "get_repo_full_names_for_team", lambda team_name: REPOS
    )
    monkeypatch.setattr(
        jobs.UpdateDependenciesReporter,
        "_state_path",
        lambda self: tmp_path / "team-dummy-update-dependencies.json",
    )


def test_report_rota_on_monday(freezer, monkeypatch, tmp_path):
    freezer.move_to("2024-03-25")  # Monday, ISO week 13
    patch_jobs(monkeypatch, tmp_path)

    blocks = json.loads(jobs.report_rota(TEAM_NAME))

    assert blocks == [
        {
            "text": {
                "text": "Team Dummy update-dependencies rota",
                "type": "plain_text",
            },
            "type": "header",
        },
        {
            "text": {"text": DUTY_TEXT, "type": "mrkdwn"},
            "type": "section",
        },
        {
            "text": {"text": ALL_OPEN_PRS_LINK_TEXT, "type": "mrkdwn"},
            "type": "section",
        },
        REPO_FIELDS_BLOCK,
    ]


def test_report_rota_includes_notes_after_the_links_for_teams_that_have_them(
    freezer, monkeypatch, tmp_path
):
    freezer.move_to("2024-03-25")  # Monday, ISO week 13
    monkeypatch.setattr(jobs, "team_members", lambda team_name: TEAM_MEMBERS)
    monkeypatch.setattr(
        jobs.repos_config, "get_repo_full_names_for_team", lambda team_name: REPOS
    )
    monkeypatch.setattr(
        jobs.UpdateDependenciesReporter,
        "_state_path",
        lambda self: tmp_path / "team-rap-update-dependencies.json",
    )

    blocks = json.loads(jobs.report_rota("Team RAP"))

    # header, duty, link, fields, notes
    assert len(blocks) == 5
    notes_text = blocks[-1]["text"]["text"]
    assert "Here's a reminder" in notes_text
    assert "  • check each repo for vulnerabilities and address" in notes_text


def test_report_rota_omits_notes_for_teams_without_them(freezer, monkeypatch, tmp_path):
    freezer.move_to("2024-03-25")  # Monday, ISO week 13
    patch_jobs(monkeypatch, tmp_path)

    blocks = json.loads(jobs.report_rota(TEAM_NAME))

    # header, duty, link, fields - nothing trailing
    assert len(blocks) == 4


def test_report_rota_always_uses_full_repo_names(freezer, monkeypatch, tmp_path):
    freezer.move_to("2024-03-25")
    repos = ["org-a/sysadmin", "org-b/sysadmin", "org-a/unique-repo"]
    monkeypatch.setattr(jobs, "team_members", lambda team_name: TEAM_MEMBERS)
    monkeypatch.setattr(
        jobs.repos_config, "get_repo_full_names_for_team", lambda team_name: repos
    )
    monkeypatch.setattr(
        jobs.UpdateDependenciesReporter,
        "_state_path",
        lambda self: tmp_path / "team-dummy-update-dependencies.json",
    )

    blocks = json.loads(jobs.report_rota(TEAM_NAME))
    repo_field_texts = [field["text"] for field in blocks[3]["fields"]]

    # Always the full "org/repo" name, even when the repo name itself (e.g.
    # "sysadmin") isn't shared with another org - no short-name shortcut.
    # report_rota() sorts repos alphabetically by full name.
    assert repo_field_texts == [
        "• <https://github.com/org-a/sysadmin/pulls|org-a/sysadmin>",
        "• <https://github.com/org-a/unique-repo/pulls|org-a/unique-repo>",
        "• <https://github.com/org-b/sysadmin/pulls|org-b/sysadmin>",
    ]


def test_report_rota_lays_out_repo_links_as_a_fields_grid(
    freezer, monkeypatch, tmp_path
):
    # Slack renders a section block's "fields" as a real 2-column grid
    # (left-aligned per column), rather than space-padded mrkdwn text.
    freezer.move_to("2024-03-25")
    repos = ["org/repo-one", "org/repo-two", "org/repo-three", "org/repo-four"]
    monkeypatch.setattr(jobs, "team_members", lambda team_name: TEAM_MEMBERS)
    monkeypatch.setattr(
        jobs.repos_config, "get_repo_full_names_for_team", lambda team_name: repos
    )
    monkeypatch.setattr(
        jobs.UpdateDependenciesReporter,
        "_state_path",
        lambda self: tmp_path / "team-dummy-update-dependencies.json",
    )

    blocks = json.loads(jobs.report_rota(TEAM_NAME))

    # report_rota() sorts repos alphabetically by full name before laying
    # them out in the fields grid.
    assert blocks[3] == {
        "type": "section",
        "fields": [
            {
                "type": "mrkdwn",
                "text": "• <https://github.com/org/repo-four/pulls|org/repo-four>",
            },
            {
                "type": "mrkdwn",
                "text": "• <https://github.com/org/repo-one/pulls|org/repo-one>",
            },
            {
                "type": "mrkdwn",
                "text": "• <https://github.com/org/repo-three/pulls|org/repo-three>",
            },
            {
                "type": "mrkdwn",
                "text": "• <https://github.com/org/repo-two/pulls|org/repo-two>",
            },
        ],
    }


def test_report_rota_chunks_repo_fields_at_slacks_ten_field_limit(
    freezer, monkeypatch, tmp_path
):
    freezer.move_to("2024-03-25")
    repos = [f"org/repo-{i:02}" for i in range(12)]
    monkeypatch.setattr(jobs, "team_members", lambda team_name: TEAM_MEMBERS)
    monkeypatch.setattr(
        jobs.repos_config, "get_repo_full_names_for_team", lambda team_name: repos
    )
    monkeypatch.setattr(
        jobs.UpdateDependenciesReporter,
        "_state_path",
        lambda self: tmp_path / "team-dummy-update-dependencies.json",
    )

    blocks = json.loads(jobs.report_rota(TEAM_NAME))

    # header, duty, link, then two fields blocks (10 + 2) - nothing trailing
    assert len(blocks) == 5
    assert len(blocks[3]["fields"]) == 10
    assert len(blocks[4]["fields"]) == 2


def test_combined_link_ors_repo_qualifiers_together(freezer, monkeypatch, tmp_path):
    # GitHub ANDs repeated qualifiers of the same type by default, so
    # multiple "repo:" filters need an explicit OR to match any PR in any
    # of the repos, rather than (impossibly) all of them at once.
    freezer.move_to("2024-03-25")
    patch_jobs(monkeypatch, tmp_path)

    blocks = json.loads(jobs.report_rota(TEAM_NAME))
    links_text = blocks[2]["text"]["text"]

    assert "repo%3Aorg%2Frepo-one+OR+repo%3Aorg%2Frepo-two" in links_text


def test_combined_link_filters_to_dependency_prs(freezer, monkeypatch, tmp_path):
    # Filter to just dependency-update PRs (the "dependencies" label, which
    # Dependabot/Renovate PRs get automatically and bot-authored PRs are
    # also labelled with), not every open PR in the team's repos.
    freezer.move_to("2024-03-25")
    patch_jobs(monkeypatch, tmp_path)

    blocks = json.loads(jobs.report_rota(TEAM_NAME))
    links_text = blocks[2]["text"]["text"]

    assert "label%3Adependencies" in links_text


def test_command_line_parser_dispatches_to_report_rota():
    args = jobs.get_command_line_parser().parse_args(["--team", TEAM_NAME, "rota"])

    assert args.function is jobs.report_rota
    assert args.team == TEAM_NAME


def test_command_line_parser_dispatches_to_advance_rota():
    args = jobs.get_command_line_parser().parse_args(["--team", TEAM_NAME, "advance"])

    assert args.function is jobs.advance_rota
    assert args.team == TEAM_NAME


def test_command_line_parser_dispatches_to_now_rota():
    args = jobs.get_command_line_parser().parse_args(["--team", TEAM_NAME, "now"])

    assert args.function is jobs.now_rota
    assert args.team == TEAM_NAME


def test_now_rota_names_who_is_on_update_dependencies_duty(
    freezer, monkeypatch, tmp_path
):
    freezer.move_to("2024-03-25")  # Monday, ISO week 13
    patch_jobs(monkeypatch, tmp_path)

    assert (
        jobs.now_rota(TEAM_NAME)
        == f"{DUMMY_B.human_readable} is on update-dependencies duty."
    )


def test_advance_rota_shifts_the_rota(freezer, monkeypatch, tmp_path):
    freezer.move_to("2024-03-25")  # Monday, ISO week 13
    patch_jobs(monkeypatch, tmp_path)

    message = jobs.advance_rota(TEAM_NAME)

    assert "Dummy C" in message
    assert "update-dependencies duty" in message

    blocks = json.loads(jobs.report_rota(TEAM_NAME))
    duty_text = blocks[1]["text"]["text"]
    assert DUMMY_C.formatted_slack_username in duty_text


def test_state_is_isolated_per_team(freezer, monkeypatch, tmp_path):
    freezer.move_to("2024-03-25")
    monkeypatch.setattr(jobs, "team_members", lambda team_name: TEAM_MEMBERS)
    monkeypatch.setattr(
        jobs.repos_config, "get_repo_full_names_for_team", lambda team_name: REPOS
    )
    monkeypatch.setattr(
        jobs.UpdateDependenciesReporter,
        "_state_path",
        lambda self: tmp_path / f"{jobs._slugify_team_name(self.team_name)}.json",
    )

    jobs.advance_rota("Team One")

    assert "Dummy C" in jobs.now_rota("Team One")
    assert "Dummy B" in jobs.now_rota("Team Two")
