import functools
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from mocket import Mocketizer, mocketize
from mocket.mockhttp import Entry

from workspace.security import jobs
from workspace.utils.github_rest_api import PagedResponse


ALERTS_FIXTURE_PATH = Path("tests/workspace/dependabot_alerts.json")
ALERTS_URL = "https://api.github.com/repos/opensafely-core/airlock/dependabot/alerts"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Each test gets its own cache file so cache state doesn't bleed between tests."""
    monkeypatch.setattr(jobs, "CACHE_PATH", tmp_path / "security_cache.json")


@pytest.fixture
def mock_alerts_endpoint():
    Entry.single_register(
        Entry.GET,
        ALERTS_URL,
        body=ALERTS_FIXTURE_PATH.read_text(),
        match_querystring=False,
    )
    with Mocketizer(strict_mode=True):
        yield


class MockRepoAlertsReporter(jobs.RepoAlertsReporter):
    """Skip the HTTP call in __init__ and let tests inject alerts via class attr."""

    counts_by_repo_full_name: dict = {}

    def __init__(self, repo_full_name, severities=None):
        self.repo_full_name = repo_full_name
        self.severities = severities or jobs.DEFAULT_SEVERITIES
        self.base_api_url = f"https://api.github.com/repos/{repo_full_name}/"
        self.dependabot_link = jobs.get_dependabot_alerts_link(repo_full_name)
        self.alerts = []

    def get_counts(self):
        zeros = {sev: 0 for sev in self.severities}
        return dict(self.counts_by_repo_full_name.get(self.repo_full_name, zeros))


def _build_config(repos_config, *, security_excluded_repos=None):
    by_org: dict = {}
    for repo, meta in repos_config.items():
        by_org.setdefault(meta["org"], {})[repo] = meta["team"]
    return {
        "teams": ["Tech shared", "Team REX", "Team RAP", "Team Prescribosaurus"],
        "shorthands": {
            "orgs": {
                "os": "opensafely",
                "osc": "opensafely-core",
                "ebm": "ebmdatalab",
                "bo": "bennettoxford",
            },
            "teams": {
                "rap": "Team RAP",
                "rex": "Team REX",
                "presc": "Team Prescribosaurus",
                "tech": "Tech shared",
            },
        },
        "repos": by_org,
        "workflows": {
            "excluded_repos": [],
            "ignored_workflows": {},
            "workflows_known_to_fail": {},
            "custom_groups": {},
        },
        "security": {"excluded_repos": security_excluded_repos or []},
    }


def use_mock_results(
    repos_config, counts_by_repo_full_name, *, security_excluded_repos=None
):
    """Patch config and RepoAlertsReporter so summary tests don't make HTTP calls."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            MockRepoAlertsReporter.counts_by_repo_full_name = counts_by_repo_full_name
            with (
                patch(
                    "workspace.utils.repos_config.load_config",
                    return_value=_build_config(
                        repos_config,
                        security_excluded_repos=security_excluded_repos,
                    ),
                ),
                patch(
                    "workspace.security.jobs.RepoAlertsReporter", MockRepoAlertsReporter
                ),
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def test_get_open_alerts_and_counts(mock_alerts_endpoint):
    reporter = jobs.RepoAlertsReporter("opensafely-core/airlock")
    assert len(reporter.alerts) == 5
    assert reporter.get_counts() == {"critical": 2, "high": 3}


def test_get_counts_skips_unknown_severity():
    with patch.object(
        jobs.RepoAlertsReporter,
        "get_open_alerts",
        return_value=[
            {"security_advisory": {"severity": "critical"}},
            {"security_advisory": {"severity": "medium"}},
            {"security_advisory": {}},
        ],
    ):
        reporter = jobs.RepoAlertsReporter("opensafely-core/airlock")
    assert reporter.get_counts() == {"critical": 1, "high": 0}


@mocketize(strict_mode=True)
def test_get_counts_no_alerts():
    Entry.single_register(
        Entry.GET,
        ALERTS_URL,
        body="[]",
        match_querystring=False,
    )
    reporter = jobs.RepoAlertsReporter("opensafely-core/airlock")
    assert reporter.get_counts() == {"critical": 0, "high": 0}


def test_cache_hit_uses_cached_alerts():
    # Pre-populate the cache; the github client returns a not_modified
    # response to simulate a 304 from the server.
    cached_alerts = [{"security_advisory": {"severity": "critical"}}]
    jobs.save_cache(
        {
            "opensafely-core/airlock|critical,high": {
                "etag": "old-etag",
                "alerts": cached_alerts,
            }
        }
    )
    with patch.object(
        jobs.github_client,
        "get_paginated_json",
        return_value=PagedResponse(
            records=iter([]), etag="old-etag", not_modified=True
        ),
    ) as mock_get:
        reporter = jobs.RepoAlertsReporter("opensafely-core/airlock")
    # The cached etag was passed through and the cached alerts re-used.
    assert mock_get.call_args.kwargs["etag"] == "old-etag"
    assert reporter.alerts == cached_alerts


def test_cache_miss_stores_response_and_etag():
    fresh_alerts = [{"security_advisory": {"severity": "high"}}]
    with patch.object(
        jobs.github_client,
        "get_paginated_json",
        return_value=PagedResponse(records=iter(fresh_alerts), etag="new-etag"),
    ):
        reporter = jobs.RepoAlertsReporter("opensafely-core/airlock")
    assert reporter.alerts == fresh_alerts
    assert jobs.load_cache() == {
        "opensafely-core/airlock|critical,high": {
            "etag": "new-etag",
            "alerts": fresh_alerts,
        }
    }


def test_cache_key_distinguishes_severities():
    # A cache entry for critical/high must not be served for an
    # all-severities request: the API filter is different so the cached
    # alerts list would be missing entries.
    jobs.save_cache(
        {
            "opensafely-core/airlock|critical,high": {
                "etag": "default-etag",
                "alerts": [{"security_advisory": {"severity": "critical"}}],
            }
        }
    )
    with patch.object(
        jobs.github_client,
        "get_paginated_json",
        return_value=PagedResponse(records=iter([]), etag="all-sev-etag"),
    ) as mock_get:
        jobs.RepoAlertsReporter(
            "opensafely-core/airlock", severities=jobs.ALL_SEVERITIES
        )
    # No cached etag was passed (different cache key for the all-severities request).
    assert mock_get.call_args.kwargs["etag"] is None


def test_report_with_alerts(mock_alerts_endpoint):
    reporter = jobs.RepoAlertsReporter("opensafely-core/airlock")
    blocks = reporter.report_blocks()
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":rotating_light: Open Critical/High Security Alerts :rotating_light: for opensafely-core/airlock",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":red_circle: 2 critical, :large_orange_circle: 3 high",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<https://github.com/opensafely-core/airlock/security/dependabot|View security alerts>",
            },
        },
    ]


@mocketize(strict_mode=True)
def test_report_no_alerts():
    Entry.single_register(
        Entry.GET,
        ALERTS_URL,
        body="[]",
        match_querystring=False,
    )
    reporter = jobs.RepoAlertsReporter("opensafely-core/airlock")
    blocks = reporter.report_blocks()
    assert (
        blocks[1]["text"]["text"]
        == ":red_circle: 0 critical, :large_orange_circle: 0 high"
    )


REPOS_CONFIG = {
    "airlock": {"org": "opensafely-core", "team": "Team RAP"},
    "ehrql": {"org": "opensafely-core", "team": "Team RAP"},
    "job-server": {"org": "opensafely-core", "team": "Team REX"},
    "documentation": {"org": "opensafely", "team": "Tech shared"},
}


def test_get_repo_full_names_for_team():
    from workspace.utils import repos_config

    with patch(
        "workspace.utils.repos_config.load_config",
        return_value=_build_config(REPOS_CONFIG),
    ):
        assert repos_config.get_repo_full_names_for_team("Team RAP") == [
            "opensafely-core/airlock",
            "opensafely-core/ehrql",
        ]
        assert repos_config.get_repo_full_names_for_team("Team Prescribosaurus") == []


def test_get_repo_full_names_for_org():
    from workspace.utils import repos_config

    with patch(
        "workspace.utils.repos_config.load_config",
        return_value=_build_config(REPOS_CONFIG),
    ):
        assert sorted(repos_config.get_repo_full_names_for_org("opensafely-core")) == [
            "opensafely-core/airlock",
            "opensafely-core/ehrql",
            "opensafely-core/job-server",
        ]
        assert repos_config.get_repo_full_names_for_org("opensafely") == [
            "opensafely/documentation"
        ]


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 2, "high": 3},
        "opensafely-core/ehrql": {"critical": 0, "high": 0},
        "opensafely-core/job-server": {"critical": 0, "high": 1},
        "opensafely/documentation": {"critical": 0, "high": 0},
    },
)
def test_summarise_team_skips_zero_alert_repos():
    blocks = jobs.summarise_team("Team RAP", jobs.DEFAULT_SEVERITIES)
    assert blocks == [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Team RAP*"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<https://github.com/opensafely-core/airlock/security/dependabot|opensafely-core/airlock>: :red_circle: 2 critical, :large_orange_circle: 3 high",
            },
        },
    ]


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 0, "high": 0},
        "opensafely-core/ehrql": {"critical": 0, "high": 0},
    },
)
def test_summarise_team_all_zero_returns_empty():
    assert jobs.summarise_team("Team RAP", jobs.DEFAULT_SEVERITIES) == []


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 1, "high": 0},
        "opensafely-core/ehrql": {"critical": 0, "high": 0},
        "opensafely-core/job-server": {"critical": 0, "high": 2},
        "opensafely/documentation": {"critical": 0, "high": 0},
    },
)
def test_summarise_all_groups_by_team():
    blocks = jobs.summarise_all(jobs.DEFAULT_SEVERITIES)
    # One top-level header, then bold subheaders per team
    headers = [b["text"]["text"] for b in blocks if b["type"] == "header"]
    subheaders = [
        b["text"]["text"]
        for b in blocks
        if b["type"] == "section" and b["text"]["text"].startswith("*")
    ]
    assert headers == [
        ":rotating_light: Open Critical/High Security Alerts :rotating_light:"
    ]
    # Subheaders appear in config.TEAMS order ("Team REX" before "Team RAP")
    assert subheaders == ["*Team REX*", "*Team RAP*"]


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 0, "high": 0},
        "opensafely-core/ehrql": {"critical": 0, "high": 0},
        "opensafely-core/job-server": {"critical": 0, "high": 0},
        "opensafely/documentation": {"critical": 0, "high": 0},
    },
)
def test_summarise_all_nothing_to_report():
    blocks = jobs.summarise_all(jobs.DEFAULT_SEVERITIES)
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":white_check_mark: No open critical or high severity alerts to report!",
            },
        }
    ]


@pytest.mark.parametrize("command", ["report", "report --target all"])
def test_all_as_target(command):
    args = jobs.get_command_line_parser().parse_args(command.split())
    with patch("workspace.security.jobs.summarise_all") as mock_summarise_all:
        mock_summarise_all.return_value = []
        jobs.main(args)
        mock_summarise_all.assert_called_once_with(jobs.DEFAULT_SEVERITIES, quiet=False)


@pytest.mark.parametrize(
    "target,resolved",
    [
        ("rap", "Team RAP"),
        ("rex", "Team REX"),
        ("presc", "Team Prescribosaurus"),
    ],
)
def test_team_as_target(target, resolved):
    args = jobs.get_command_line_parser().parse_args(["report", "--target", target])
    with patch("workspace.security.jobs.summarise_team") as mock_summarise_team:
        mock_summarise_team.return_value = []
        jobs.main(args)
        mock_summarise_team.assert_called_once_with(resolved, jobs.DEFAULT_SEVERITIES)


@pytest.mark.parametrize("org", ["opensafely-core", "osc"])
def test_org_as_target(org):
    args = jobs.get_command_line_parser().parse_args(["report", "--target", org])
    with patch("workspace.security.jobs.summarise_org") as mock_summarise_org:
        mock_summarise_org.return_value = []
        jobs.main(args)
        mock_summarise_org.assert_called_once_with(
            "opensafely-core", jobs.DEFAULT_SEVERITIES
        )


@pytest.mark.parametrize(
    "target, parsed",
    [
        ("opensafely-core/airlock", "opensafely-core/airlock"),
        ("osc/airlock", "opensafely-core/airlock"),
        ("airlock", "opensafely-core/airlock"),
        ("opensafely/unknown-repo", "opensafely/unknown-repo"),
        ("os/unknown-repo", "opensafely/unknown-repo"),
    ],
)
def test_repo_as_target(target, parsed):
    args = jobs.get_command_line_parser().parse_args(["report", "--target", target])
    with patch("workspace.security.jobs.RepoAlertsReporter") as MockReporter:
        MockReporter.return_value.report_blocks.return_value = []
        MockReporter.return_value.get_counts.return_value = {"critical": 0, "high": 0}
        jobs.main(args)
        MockReporter.assert_called_once_with(parsed, severities=jobs.DEFAULT_SEVERITIES)


def test_list_of_teams_as_target():
    args = jobs.get_command_line_parser().parse_args(["report", "--target", "rap rex"])
    with patch("workspace.security.jobs.summarise_team") as mock_summarise_team:
        mock_summarise_team.return_value = []
        jobs.main(args)
        mock_summarise_team.assert_any_call("Team RAP", jobs.DEFAULT_SEVERITIES)
        mock_summarise_team.assert_called_with("Team REX", jobs.DEFAULT_SEVERITIES)
        assert mock_summarise_team.call_count == 2


def test_list_of_orgs_as_target():
    args = jobs.get_command_line_parser().parse_args(["report", "--target", "osc ebm"])
    with patch("workspace.security.jobs.summarise_org") as mock_summarise_org:
        mock_summarise_org.return_value = []
        jobs.main(args)
        mock_summarise_org.assert_any_call("opensafely-core", jobs.DEFAULT_SEVERITIES)
        mock_summarise_org.assert_called_with("ebmdatalab", jobs.DEFAULT_SEVERITIES)
        assert mock_summarise_org.call_count == 2


@pytest.mark.parametrize(
    "target",
    ["some/invalid/input", "totally-unknown"],
)
def test_invalid_target(target):
    args = jobs.get_command_line_parser().parse_args(["report", "--target", target])
    blocks = json.loads(jobs.main(args))
    assert blocks[0] == {
        "type": "header",
        "text": {"type": "plain_text", "text": f"{target} was not recognised"},
    }


@pytest.mark.parametrize(
    "target",
    ["rap osc", "rap airlock", "osc airlock"],
)
def test_mixed_list_as_target(target):
    args = jobs.get_command_line_parser().parse_args(["report", "--target", target])
    blocks = json.loads(jobs.main(args))
    assert blocks[0] == {
        "type": "header",
        "text": {"type": "plain_text", "text": "Invalid list of targets"},
    }


def test_catch_unhandled_error():
    args = jobs.get_command_line_parser().parse_args(["report", "--target", "all"])
    with patch(
        "workspace.security.jobs.summarise_all",
        side_effect=Exception("boom"),
    ):
        blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "An error occurred reporting security alerts for all",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "boom"},
        },
    ]


def test_print_usage():
    text = jobs.get_usage_text(None)
    assert text.startswith("Usage for `security report [target]`:")
    assert "Team RAP" in text


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 2, "high": 3},
        "opensafely-core/ehrql": {"critical": 0, "high": 0},
    },
)
def test_main_show_team_wraps_top_header():
    args = jobs.get_command_line_parser().parse_args(["report", "--target", "rap"])
    blocks = json.loads(jobs.main(args))
    assert blocks[0] == {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": ":rotating_light: Open Critical/High Security Alerts :rotating_light:",
        },
    }
    assert blocks[1] == {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*Team RAP*"},
    }
    assert blocks[2]["text"]["text"].startswith(
        "<https://github.com/opensafely-core/airlock/security/dependabot|opensafely-core/airlock>:"
    )


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 1, "high": 0},
        "opensafely-core/job-server": {"critical": 0, "high": 2},
        "opensafely-core/ehrql": {"critical": 0, "high": 0},
    },
)
def test_main_show_org_wraps_top_header():
    args = jobs.get_command_line_parser().parse_args(["report", "--target", "osc"])
    blocks = json.loads(jobs.main(args))
    assert (
        blocks[0]["text"]["text"]
        == ":rotating_light: Open Critical/High Security Alerts :rotating_light:"
    )
    assert blocks[1]["text"]["text"] == "*opensafely-core*"
    body_texts = [b["text"]["text"] for b in blocks[2:]]
    assert any("opensafely-core/airlock" in t for t in body_texts)
    assert any("opensafely-core/job-server" in t for t in body_texts)


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 1, "high": 0},
        "opensafely-core/ehrql": {"critical": 0, "high": 2},
    },
)
def test_main_show_repo_list_has_top_header_no_subheader():
    args = jobs.get_command_line_parser().parse_args(
        ["report", "--target", "airlock ehrql"]
    )
    blocks = json.loads(jobs.main(args))
    assert (
        blocks[0]["text"]["text"]
        == ":rotating_light: Open Critical/High Security Alerts :rotating_light:"
    )
    # No subheader between top header and repo lines
    assert not blocks[1]["text"]["text"].startswith("*")


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 0, "high": 0},
        "opensafely-core/ehrql": {"critical": 0, "high": 0},
    },
)
def test_main_show_team_no_alerts():
    args = jobs.get_command_line_parser().parse_args(["report", "--target", "rap"])
    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":white_check_mark: No open critical or high severity alerts to report!",
            },
        }
    ]


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 0, "high": 0},
        "opensafely-core/ehrql": {"critical": 0, "high": 0},
        "opensafely-core/job-server": {"critical": 0, "high": 0},
        "opensafely/documentation": {"critical": 0, "high": 0},
    },
)
def test_main_quiet_no_alerts_returns_empty_string():
    args = jobs.get_command_line_parser().parse_args(
        ["report", "--target", "all", "--quiet"]
    )
    assert jobs.main(args) == ""


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 1, "high": 0},
        "opensafely-core/ehrql": {"critical": 0, "high": 0},
        "opensafely-core/job-server": {"critical": 0, "high": 0},
        "opensafely/documentation": {"critical": 0, "high": 0},
    },
)
def test_main_quiet_with_alerts_still_reports():
    args = jobs.get_command_line_parser().parse_args(
        ["report", "--target", "all", "--quiet"]
    )
    blocks = json.loads(jobs.main(args))
    assert blocks[0]["text"]["text"] == (
        ":rotating_light: Open Critical/High Security Alerts :rotating_light:"
    )


def test_main_quiet_single_repo_no_alerts_returns_empty_string():
    args = jobs.get_command_line_parser().parse_args(
        ["report", "--target", "airlock", "--quiet"]
    )
    with patch("workspace.security.jobs.RepoAlertsReporter") as MockReporter:
        MockReporter.return_value.get_counts.return_value = {"critical": 0, "high": 0}
        assert jobs.main(args) == ""


def test_main_quiet_single_repo_with_alerts_still_reports():
    args = jobs.get_command_line_parser().parse_args(
        ["report", "--target", "airlock", "--quiet"]
    )
    with patch("workspace.security.jobs.RepoAlertsReporter") as MockReporter:
        MockReporter.return_value.get_counts.return_value = {"critical": 1, "high": 0}
        MockReporter.return_value.report_blocks.return_value = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "alerts!"}}
        ]
        assert jobs.main(args) != ""


def test_invalid_target_message_references_usage():
    args = jobs.get_command_line_parser().parse_args(["report", "--target", "nope"])
    blocks = json.loads(jobs.main(args))
    assert (
        "Run `@test_username security usage` to see the valid values"
        in blocks[1]["text"]["text"]
    )


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {
            "critical": 1,
            "high": 0,
            "medium": 2,
            "low": 0,
        },
        "opensafely-core/ehrql": {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 1,
        },
    },
)
def test_main_all_severities_uses_all_severity_header():
    args = jobs.get_command_line_parser().parse_args(
        ["report", "--target", "rap", "--all-severities"]
    )
    blocks = json.loads(jobs.main(args))
    assert blocks[0]["text"]["text"] == (
        ":rotating_light: Open Security Alerts :rotating_light:"
    )
    # Each summary line should list all severities with non-zero counts
    body_texts = [b["text"]["text"] for b in blocks[1:]]
    assert any("medium" in t for t in body_texts)
    assert any("low" in t for t in body_texts)


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        },
        "opensafely-core/ehrql": {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        },
    },
)
def test_main_all_severities_nothing_to_report_message():
    args = jobs.get_command_line_parser().parse_args(
        ["report", "--target", "rap", "--all-severities"]
    )
    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":white_check_mark: No open security alerts to report!",
            },
        }
    ]


def test_main_all_severities_single_repo_header_label():
    args = jobs.get_command_line_parser().parse_args(
        ["report", "--target", "airlock", "--all-severities"]
    )
    with patch("workspace.security.jobs.RepoAlertsReporter") as MockReporter:
        MockReporter.return_value.severities = jobs.ALL_SEVERITIES
        MockReporter.return_value.get_counts.return_value = dict.fromkeys(
            jobs.ALL_SEVERITIES, 0
        )
        MockReporter.return_value.report_blocks.return_value = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": (
                        "Open all-severity security alerts for opensafely-core/airlock"
                    ),
                },
            }
        ]
        result = jobs.main(args)
    MockReporter.assert_called_once_with(
        "opensafely-core/airlock", severities=jobs.ALL_SEVERITIES
    )
    blocks = json.loads(result)
    assert (
        blocks[0]["text"]["text"]
        == "Open all-severity security alerts for opensafely-core/airlock"
    )


@pytest.mark.parametrize(
    "text, expected_job_type",
    [
        ("security report", "security_report_all_targets"),
        ("security report airlock", "security_report"),
        ("security check", "security_check_all_targets"),
        ("security check airlock", "security_check"),
        ("security report-all", "security_report_all_severities_all_targets"),
        ("security report-all airlock", "security_report_all_severities"),
    ],
)
def test_security_slack_routing(text, expected_job_type):
    """Sanity-check that each verb routes to the expected job."""
    from bennettbot.job_configs import config as bot_config

    matched = next(sc for sc in bot_config["slack"] if sc["regex"].match(text))
    assert matched["job_type"] == expected_job_type


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 1, "high": 0},
        "opensafely-core/ehrql": {"critical": 0, "high": 5},
        "opensafely-core/job-server": {"critical": 0, "high": 2},
        "opensafely/documentation": {"critical": 0, "high": 0},
    },
    security_excluded_repos=["opensafely-core/ehrql"],
)
def test_excluded_repos_skipped_in_team_summary():
    blocks = jobs.summarise_team("Team RAP", jobs.DEFAULT_SEVERITIES)
    rendered = " ".join(b["text"]["text"] for b in blocks)
    assert "ehrql" not in rendered
    assert "airlock" in rendered


@use_mock_results(
    REPOS_CONFIG,
    {
        "opensafely-core/airlock": {"critical": 0, "high": 0},
        "opensafely-core/ehrql": {"critical": 0, "high": 0},
        "opensafely-core/job-server": {"critical": 0, "high": 0},
        "opensafely/documentation": {"critical": 0, "high": 0},
    },
    security_excluded_repos=["opensafely-core/airlock"],
)
def test_excluded_repos_rejected_as_explicit_target():
    args = jobs.get_command_line_parser().parse_args(
        ["report", "--target", "opensafely-core/airlock"]
    )
    blocks = json.loads(jobs.main(args))
    assert "was not recognised" in blocks[0]["text"]["text"]
