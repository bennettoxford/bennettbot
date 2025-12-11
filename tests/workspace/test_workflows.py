import functools
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from mocket import Mocket, Mocketizer, mocketize
from mocket.mockhttp import Entry

from workspace.workflows import jobs


# Use current year to avoid SystemTimeWarning when frozen time is too far in the past
THIS_YEAR = datetime.now().year

WORKFLOWS_MAIN = {
    82728346: "CI",
    88048829: "CodeQL",
    94331150: "Trigger a deploy of opensafely documentation site",
    108457763: "Dependabot Updates",
    113602598: "Local job-server setup CI",
}
WORKFLOWS = {
    **WORKFLOWS_MAIN,
    94122733: "Docs",
}

CACHE = {
    "opensafely-core/airlock": {
        "version": "1",
        "timestamp": f"{THIS_YEAR}-01-15T09:00:08Z",
        # from fixture data in runs.json
        "conclusions": {
            "82728346": [
                "success",
                "https://github.com/opensafely-core/airlock/actions/runs/10831112419",
            ],
            "88048829": [
                "success",
                "https://github.com/opensafely-core/airlock/actions/runs/10831112372",
            ],
            "94331150": [
                "success",
                "https://github.com/opensafely-core/airlock/actions/runs/10831195069",
            ],
            "108457763": [
                "success",
                "https://github.com/opensafely-core/airlock/actions/runs/10876622800",
            ],
            "113602598": [
                "success",
                "https://github.com/opensafely-core/airlock/actions/runs/10876792689",
            ],
        },
    }
}
RESULT_PATCH_SETTINGS = {
    "org": "opensafely-core",
    "repo": "airlock",
    "team": "Team RAP",
    "conclusions": [["success", "http://example.com"]] * 5,
}
RESULT_BLOCK = {
    "type": "section",
    "text": {
        "type": "mrkdwn",
        "text": f"<https://github.com/opensafely-core/airlock/actions?query=branch%3Amain|opensafely-core/airlock>: {'<http://example.com|:large_green_circle:>' * 5}",
    },
}


@pytest.fixture
def cache_path(tmp_path):
    yield tmp_path / "test_cache.json"


@pytest.fixture
def mock_airlock_reporter():
    # Workflow IDs and names
    Entry.single_register(
        Entry.GET,
        "https://api.github.com/repos/opensafely-core/airlock/actions/workflows?format=json",
        body=Path("tests/workspace/workflows.json").read_text(),
        match_querystring=True,
    )

    # Workflow runs
    Entry.single_register(
        Entry.GET,
        "https://api.github.com/repos/opensafely-core/airlock/actions/runs?per_page=100&format=json",
        body=Path("tests/workspace/runs.json").read_text(),
        match_querystring=False,  # Test the querystring separately
    )
    with Mocketizer(strict_mode=True):
        reporter = jobs.RepoWorkflowReporter("opensafely-core/airlock")
        reporter.cache = {}  # Drop the cache and test _load_cache_for_repo separately
        yield reporter


class MockRepoWorkflowReporter(jobs.RepoWorkflowReporter):
    # A mock class to allow us to vary the conclusions returned by get_latest_conclusions.

    def get_workflows(self) -> dict:
        return WORKFLOWS_MAIN

    def get_runs(self, since_last_retrieval) -> list:
        # Have no new runs so that results are read from a separately patched mock cache
        return []

    def write_cache_to_file(self):
        # Skip writing to the cache file as this is already tested separately
        pass


def use_mock_results(patch_settings):
    def decorator_use_mock_results(func):
        @functools.wraps(func)
        def wrapper_use_mock_results(*args, **kwargs):
            # Mock config
            mock_repos_config = {
                r["repo"]: {"org": r["org"], "team": r["team"]} for r in patch_settings
            }
            # Mock cache
            keys = sorted(list(WORKFLOWS_MAIN.keys()))
            mock_cache = {
                f"{r['org']}/{r['repo']}": {
                    "version": "1",
                    "timestamp": f"{THIS_YEAR}-01-15T09:00:08Z",
                    "conclusions": {
                        str(keys[i]): conc for i, conc in enumerate(r["conclusions"])
                    },
                }
                for r in patch_settings
            }
            # Patch the config and use results from the mock cache
            with (
                patch("workspace.workflows.config.REPOS", mock_repos_config),
                patch("workspace.workflows.jobs.load_cache", return_value=mock_cache),
                patch(
                    "workspace.workflows.jobs.RepoWorkflowReporter",
                    MockRepoWorkflowReporter,
                ),
            ):
                return func(*args, **kwargs)

        return wrapper_use_mock_results

    return decorator_use_mock_results


def test_print_key():
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Workflow status emoji key",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":large_green_circle:=Success",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":large_yellow_circle:=Running",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":red_circle:=Failure",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":white_circle:=Skipped",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":heavy_multiplication_x:=Cancelled",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":ghost:=Missing",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":grey_question:=Other",
            },
        },
    ]
    assert json.loads(jobs.get_text_blocks_for_key(None)) == blocks


def test_print_usage():
    usage_text = jobs.get_usage_text(None)
    with pytest.raises(json.JSONDecodeError):
        json.loads(usage_text)
    assert usage_text.startswith(
        "Usage for `show [target]` (The behaviour for `show-failed [target]` is the same, but skips repos whose workflows are all successful):"
    )


@pytest.mark.parametrize("command", ["show", "show --target all"])
def test_all_as_target(command):
    args = jobs.get_command_line_parser().parse_args(command.split())
    args = jobs.get_command_line_parser().parse_args("show --target all".split())

    with patch("workspace.workflows.jobs.summarise_all") as mock_summarise_all:
        jobs.main(args)
        mock_summarise_all.assert_called_once_with(False)


@pytest.mark.parametrize("org", ["opensafely-core", "osc"])
def test_org_as_target(org):
    args = jobs.get_command_line_parser().parse_args(f"show --target {org}".split())

    with patch("workspace.workflows.jobs.summarise_org") as mock_summarise_org:
        jobs.main(args)
        mock_summarise_org.assert_called_once_with("opensafely-core", False)


@pytest.mark.parametrize(
    "repo, parsed",
    [
        # Known org, known repo
        ("opensafely-core/airlock", "opensafely-core/airlock"),
        ("osc/airlock", "opensafely-core/airlock"),
        ("airlock", "opensafely-core/airlock"),
        # Known org, unknown repo
        ("opensafely/unknown-repo", "opensafely/unknown-repo"),
        ("os/unknown-repo", "opensafely/unknown-repo"),
    ],
)
def test_repo_as_target(repo, parsed):
    args = jobs.get_command_line_parser().parse_args(f"show --target {repo}".split())

    with patch("workspace.workflows.jobs.RepoWorkflowReporter") as MockReporter:
        jobs.main(args)
        MockReporter.assert_called_once_with(parsed)


def test_website_repo_as_target():
    args = jobs.get_command_line_parser().parse_args(
        "show --target http://bennett.ox.ac.uk".split()
    )
    with patch("workspace.workflows.jobs.RepoWorkflowReporter") as MockReporter:
        jobs.main(args)
        MockReporter.assert_called_once_with("ebmdatalab/bennett.ox.ac.uk")


@pytest.mark.parametrize(
    "cli_args",
    [
        ["show", "--target", "osc ebm"],
        ["show", "--target", "osc  ebm"],
        ["show", "--target", " osc ebm"],
    ],
)
def test_list_of_orgs_as_target(cli_args):
    args = jobs.get_command_line_parser().parse_args(cli_args)
    with patch("workspace.workflows.jobs.summarise_org") as mock_summarise_org:
        jobs.main(args)
        mock_summarise_org.assert_any_call("opensafely-core", False)
        mock_summarise_org.assert_called_with("ebmdatalab", False)
        assert mock_summarise_org.call_count == 2


def test_list_of_repos_as_target():
    args = jobs.get_command_line_parser().parse_args(
        ["show", "--target", "airlock bennett.ox.ac.uk"]
    )
    with patch("workspace.workflows.jobs._summarise") as mock__summarise:
        jobs.main(args)
        mock__summarise.assert_called_once_with(
            "Workflows summary",
            [
                "opensafely-core/airlock",
                "ebmdatalab/bennett.ox.ac.uk",
            ],
            False,
        )


@pytest.mark.parametrize(
    "cli_args",
    [
        ["show", "--target", "some/invalid/input"],
        ["show", "--target", "osc some/invalid/input"],
    ],
)
def test_invalid_target(cli_args):
    args = jobs.get_command_line_parser().parse_args(cli_args)
    blocks = json.loads(jobs.main(args))
    assert blocks[0] == {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "some/invalid/input was not recognised",
        },
    }


def test_mixed_list_as_target():
    args = jobs.get_command_line_parser().parse_args(
        ["show", "--target", "osc airlock"]
    )
    blocks = json.loads(jobs.main(args))
    assert blocks[0] == {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Invalid list of targets",
        },
    }


def test_catch_unhandled_error():
    args = jobs.get_command_line_parser().parse_args(
        "show --target some/invalid/input".split()
    )
    with patch(
        "workspace.workflows.jobs.report_invalid_target",
        return_value=None,
        side_effect=Exception("Unknown error"),
    ):
        blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "An error occurred reporting workflows for some/invalid/input",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Unknown error",
            },
        },
    ]


@mocketize(strict_mode=True)
def test_get_workflows():
    # get_workflows is called in __init__, so create the instance here
    Entry.single_register(
        Entry.GET,
        "https://api.github.com/repos/opensafely-core/airlock/actions/workflows?format=json",
        match_querystring=True,
        body=Path("tests/workspace/workflows.json").read_text(),
    )
    reporter = jobs.RepoWorkflowReporter("opensafely-core/airlock")
    assert len(reporter.workflows) == 5
    assert reporter.workflows == WORKFLOWS_MAIN


def test_cache_file_does_not_exist(mock_airlock_reporter, cache_path):
    assert not cache_path.exists()
    with patch("workspace.workflows.jobs.CACHE_PATH", cache_path):
        assert jobs.load_cache() == {}
        assert mock_airlock_reporter._load_cache_for_repo() == {}


def test_repo_not_cached(mock_airlock_reporter, cache_path):
    # The cache file exists but there is no record for this repo
    mock_cache = {"another/repo": CACHE["opensafely-core/airlock"]}
    with open(cache_path, "w") as f:
        json.dump(mock_cache, f)
    with patch("workspace.workflows.jobs.CACHE_PATH", cache_path):
        assert mock_airlock_reporter._load_cache_for_repo() == {}


def test_cache_no_version(mock_airlock_reporter, cache_path):
    mock_cache = {
        "opensafely-core/airlock": {
            "timestamp": f"{THIS_YEAR}-01-15T09:00:08Z",
            "conclusions": {
                "1": {"82728346": ["success", "https://example.com/run/1"]}
            },
        }
    }
    with open(cache_path, "w") as f:
        json.dump(mock_cache, f)

    with patch("workspace.workflows.jobs.CACHE_PATH", cache_path):
        cache = mock_airlock_reporter._load_cache_for_repo()
    assert cache == {}


def test_cache_version(mock_airlock_reporter, cache_path):
    mock_cache = {
        "opensafely-core/airlock": {
            "version": mock_airlock_reporter.cache_version,
            "timestamp": f"{THIS_YEAR}-01-15T09:00:08Z",
            "conclusions": {
                "1": {"82728346": ["success", "https://example.com/run/1"]}
            },
        }
    }
    with open(cache_path, "w") as f:
        json.dump(mock_cache, f)

    with patch("workspace.workflows.jobs.CACHE_PATH", cache_path):
        cache = mock_airlock_reporter._load_cache_for_repo()
    assert cache == mock_cache["opensafely-core/airlock"]
    assert mock_airlock_reporter.cache_version == cache["version"]

    mock_airlock_reporter.cache_version = "foo"
    with patch("workspace.workflows.jobs.CACHE_PATH", cache_path):
        new_cache = mock_airlock_reporter._load_cache_for_repo()
    assert new_cache == {}


def test_get_runs_since_last_retrieval(mock_airlock_reporter, cache_path):
    # Create the cache and test that it is loaded
    with open(cache_path, "w") as f:
        json.dump(CACHE, f)
    with patch("workspace.workflows.jobs.CACHE_PATH", cache_path):
        mock_airlock_reporter.cache = mock_airlock_reporter._load_cache_for_repo()
    assert mock_airlock_reporter.cache == CACHE["opensafely-core/airlock"]

    mock_airlock_reporter.get_runs(since_last_retrieval=True)
    assert Mocket.last_request().querystring == {
        "branch": ["main"],
        "per_page": ["100"],
        "format": ["json"],
        "created": [f">={THIS_YEAR}-01-15T09:00:08Z"],
    }


def test_all_workflows_found(mock_airlock_reporter, cache_path):
    with patch("workspace.workflows.jobs.CACHE_PATH", cache_path):
        conclusions = mock_airlock_reporter.get_latest_conclusions()
    assert conclusions.keys() == WORKFLOWS_MAIN.keys()
    assert "created" not in Mocket.last_request().querystring


def test_some_workflows_ignored(mock_airlock_reporter, cache_path):
    # Have the first run in runs.json be for an ignored workflow
    mock_airlock_reporter.workflows.pop(113602598)
    mock_airlock_reporter.workflow_ids = set(mock_airlock_reporter.workflows.keys())
    with patch("workspace.workflows.jobs.CACHE_PATH", cache_path):
        conclusions = mock_airlock_reporter.get_latest_conclusions()
    assert len(conclusions) == len(WORKFLOWS_MAIN) - 1
    assert 113602598 not in conclusions


def test_some_workflows_not_found(mock_airlock_reporter, cache_path):
    mock_airlock_reporter.workflows[1234] = "Workflow that only exists in the cache"
    mock_airlock_reporter.cache = {
        "version": mock_airlock_reporter.cache_version,
        "timestamp": f"{THIS_YEAR}-01-15T09:00:08Z",
        "conclusions": {"1234": ["running", "http://example.com/run/1"]},
    }

    mock_airlock_reporter.workflows[5678] = "Workflow that will not be found"
    mock_airlock_reporter.workflow_ids = set(mock_airlock_reporter.workflows.keys())
    with patch("workspace.workflows.jobs.CACHE_PATH", cache_path):
        conclusions = mock_airlock_reporter.get_latest_conclusions()
    assert len(mock_airlock_reporter.workflow_ids) == 7
    conclusion_statuses = {key: val[0] for key, val in conclusions.items()}
    assert conclusion_statuses == {
        **{key: "success" for key in WORKFLOWS_MAIN.keys()},
        1234: "running",
        5678: "missing",
    }


@pytest.mark.parametrize(
    "conclusion,created_in_querystring", [("success", True), ("failure", False)]
)
def test_get_runs_beyond_last_retrieval_if_not_all_successful(
    conclusion, created_in_querystring, mock_airlock_reporter, cache_path
):
    mock_airlock_reporter.workflows[1234] = "Some failing workflow"
    mock_airlock_reporter.cache = {
        "version": mock_airlock_reporter.cache_version,
        "timestamp": f"{THIS_YEAR}-01-15T09:00:08Z",
        "conclusions": {"1234": [conclusion, "https://example.com/run/1"]},
    }
    mock_airlock_reporter.workflow_ids = set(mock_airlock_reporter.workflows.keys())
    with patch("workspace.workflows.jobs.CACHE_PATH", cache_path):
        conclusions = mock_airlock_reporter.get_latest_conclusions()
    assert len(mock_airlock_reporter.workflow_ids) == 6
    conclusion_statuses = {key: val[0] for key, val in conclusions.items()}
    assert conclusion_statuses == {
        **{key: "success" for key in WORKFLOWS_MAIN.keys()},
        1234: conclusion,
    }

    querystring = Mocket.last_request().querystring
    assert ("created" in querystring) == created_in_querystring


@patch("workspace.workflows.jobs.RepoWorkflowReporter.write_cache_to_file")
def test_cache_creation(mock_write, mock_airlock_reporter, freezer):
    mock_write.return_value = None  # Disable writing to file and test separately
    assert mock_airlock_reporter.cache == {}
    freezer.move_to(f"{THIS_YEAR}-01-15 09:00:08")
    mock_airlock_reporter.get_latest_conclusions()
    assert mock_airlock_reporter.cache == CACHE["opensafely-core/airlock"]


def test_write_to_cache_file(mock_airlock_reporter, cache_path):
    mock_airlock_reporter.cache = CACHE["opensafely-core/airlock"]
    with patch("workspace.workflows.jobs.CACHE_PATH", cache_path):
        mock_airlock_reporter.write_cache_to_file()
    assert json.loads(cache_path.read_text()) == CACHE


@pytest.mark.parametrize(
    "run, conclusion",
    [
        (
            {
                "status": "completed",
                "conclusion": "success",
                "html_url": "http://example.com/run/1",
            },
            ["success", "http://example.com/run/1"],
        ),
        (
            {
                "status": "in_progress",
                "conclusion": None,
                "html_url": "http://example.com/run/2",
            },
            ["running", "http://example.com/run/2"],
        ),
        (
            {
                "status": "completed",
                "conclusion": "failure",
                "html_url": "http://example.com/run/3",
            },
            ["failure", "http://example.com/run/3"],
        ),
        (
            {
                "status": "completed",
                "conclusion": "skipped",
                "html_url": "http://example.com/run/4",
            },
            ["skipped", "http://example.com/run/4"],
        ),
        ({"status": None, "conclusion": None, "html_url": None}, ["None", ""]),
        ({"status": None, "conclusion": None}, ["None", ""]),
    ],
)
def test_get_conclusion_for_run(run, conclusion):
    assert jobs.RepoWorkflowReporter.get_conclusion_for_run(run) == conclusion


@pytest.mark.parametrize(
    "conclusion, emoji_link",
    [
        (
            ["success", "http://example.com/run/1"],
            "<http://example.com/run/1|:large_green_circle:>",
        ),
        (["None", ""], ":grey_question:"),
        (["", ""], ":grey_question:"),
    ],
)
def test_get_summary_block(conclusion, emoji_link):
    conclusions = [conclusion] * 5
    block = jobs.get_summary_block("opensafely-core/airlock", conclusions)
    assert block == {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"<https://github.com/opensafely-core/airlock/actions?query=branch%3Amain|opensafely-core/airlock>: {emoji_link * 5}",
        },
    }


@mocketize(strict_mode=True)
@pytest.mark.parametrize(
    "conclusion, reported, emoji",
    [
        (
            ["success", "http://example.com/run/1"],
            "<http://example.com/run/1|Success>",
            ":large_green_circle:",
        ),
        (
            ["startup_failure", "http://example.com/run/2"],
            "<http://example.com/run/2|Startup Failure>",
            ":grey_question:",
        ),  # Handle underscore
        (["None", ""], "None", ":grey_question:"),
        (["", ""], "", ":grey_question:"),
    ],
)
@patch("workspace.workflows.jobs.RepoWorkflowReporter.get_latest_conclusions")
def test_main_show_repo(mock_conclusions, conclusion, reported, emoji):
    # Call main for a single repo (opensafely-core/airlock)
    # No need to mock CACHE_PATH since get_latest_conclusions is mocked
    Entry.single_register(
        Entry.GET,
        "https://api.github.com/repos/opensafely-core/airlock/actions/workflows?format=json",
        match_querystring=True,
        body=Path("tests/workspace/workflows.json").read_text(),
    )
    mock_conclusions.return_value = {
        key: conclusion for key in sorted(list(WORKFLOWS_MAIN.keys()))
    }
    status = f"{emoji} {reported}"
    args = jobs.get_command_line_parser().parse_args(
        "show --target opensafely-core/airlock".split()
    )
    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Workflows for opensafely-core/airlock",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"CI: {status}\nCodeQL: {status}\nTrigger a deploy of opensafely documentation site: {status}\nDependabot Updates: {status}\nLocal job-server setup CI: {status}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<https://github.com/opensafely-core/airlock/actions?query=branch%3Amain|View Github Actions>",
            },
        },
    ]


@use_mock_results(
    [
        RESULT_PATCH_SETTINGS,
        {
            "org": "opensafely-core",
            "repo": "failing-repo",
            "team": "Team REX",
            "conclusions": [["failure", "http://example.com/run/1"]] * 5,
        },
    ]
)
def test_main_show_org():
    # Call main for an organisation without skipping successful workflows
    # The failing repo should appear first
    args = jobs.get_command_line_parser().parse_args("show --target osc".split())

    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Workflows for opensafely-core repos",
            },
        },
        {  # Failing repo should appear first
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<https://github.com/opensafely-core/failing-repo/actions?query=branch%3Amain|opensafely-core/failing-repo>: {'<http://example.com/run/1|:red_circle:>' * 5}",
            },
        },
        RESULT_BLOCK,
    ]


@use_mock_results(
    [
        RESULT_PATCH_SETTINGS,
        {
            "org": "opensafely",
            "repo": "failing-repo",
            "team": "Team RAP",
            "conclusions": [["failure", "http://example.com/run/1"]] * 5,
        },
    ]
)
def test_main_show_list_of_orgs():
    args = jobs.get_command_line_parser().parse_args(["show", "--target", "os osc"])

    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Workflows for opensafely repos",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<https://github.com/opensafely/failing-repo/actions?query=branch%3Amain|opensafely/failing-repo>: {'<http://example.com/run/1|:red_circle:>' * 5}",
            },
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Workflows for opensafely-core repos",
            },
        },
        RESULT_BLOCK,
    ]


@use_mock_results(
    [
        RESULT_PATCH_SETTINGS,
        {
            "org": "opensafely",
            "repo": "failing-repo",
            "team": "Team RAP",
            "conclusions": [["failure", "http://example.com/run/1"]] * 5,
        },
    ]
)
def test_main_show_list_of_repos():
    args = jobs.get_command_line_parser().parse_args(
        ["show", "--target", "airlock failing-repo"]
    )

    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Workflows summary",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<https://github.com/opensafely/failing-repo/actions?query=branch%3Amain|opensafely/failing-repo>: {'<http://example.com/run/1|:red_circle:>' * 5}",
            },
        },
        RESULT_BLOCK,
    ]


@use_mock_results(
    [
        RESULT_PATCH_SETTINGS,
        {
            "org": "opensafely",
            "repo": "documentation",
            "team": "Team REX",
            "conclusions": [["success", "http://example.com/run/1"]] * 5,
        },
    ]
)
def test_main_show_all():
    # Call main for all repos without skipping successful workflows
    args = jobs.get_command_line_parser().parse_args("show".split())
    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Workflows for Team REX",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<https://github.com/opensafely/documentation/actions?query=branch%3Amain|opensafely/documentation>: {'<http://example.com/run/1|:large_green_circle:>' * 5}",
            },
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Workflows for Team RAP",
            },
        },
        RESULT_BLOCK,
    ]


@patch(
    "workspace.workflows.config.WORKFLOWS_KNOWN_TO_FAIL",
    {
        "opensafely/failing-repo": [82728346, 88048829, 94331150, 108457763, 113602598],
    },
)
@use_mock_results(
    [
        RESULT_PATCH_SETTINGS,
        {
            "org": "opensafely",
            "repo": "failing-repo",
            "team": "Team REX",
            "conclusions": [["failure", "http://example.com/run/1"]] * 5,
        },
    ]
)
def test_main_show_all_skip_failures():
    # Call main for all repos without skipping successful workflows
    # Since all workflows in failing-repo are known to fail, it should be skipped entirely
    args = jobs.get_command_line_parser().parse_args("show".split())
    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {  # Only the Team RAP section should appear
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Workflows for Team RAP",
            },
        },
        RESULT_BLOCK,
    ]


@use_mock_results(
    [
        RESULT_PATCH_SETTINGS,
        {
            "org": "opensafely",
            "repo": "documentation",
            "team": "Team REX",
            "conclusions": [["success", "http://example.com/run/1"]] * 5,
        },
    ]
)
def test_main_show_failed_empty():
    # Call main for all repos with skipping successful workflows
    # No failed workflows so state so
    args = jobs.get_command_line_parser().parse_args("show --skip-successful".split())
    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "No workflow failures to report!",
            },
        },
    ]


@use_mock_results(
    [
        RESULT_PATCH_SETTINGS,
        {
            "org": "opensafely",
            "repo": "failing-repo",
            "team": "Team REX",
            "conclusions": [["failure", "http://example.com/run/1"]] * 5,
        },
    ]
)
def test_main_show_failed_found():
    # Call main for all repos with skipping successful workflows
    # Only the failing repo should appear
    args = jobs.get_command_line_parser().parse_args("show --skip-successful".split())

    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {  # Only the Team REX section should appear
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Workflows for Team REX",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<https://github.com/opensafely/failing-repo/actions?query=branch%3Amain|opensafely/failing-repo>: {'<http://example.com/run/1|:red_circle:>' * 5}",
            },
        },
    ]


@patch(
    "workspace.workflows.config.WORKFLOWS_KNOWN_TO_FAIL",
    {
        # Second-last workflow is known to fail
        "opensafely-core/airlock": [108457763],
        "opensafely/failing-repo": [108457763],
    },
)
@use_mock_results(
    [
        {
            "org": "opensafely-core",
            "repo": "airlock",
            "team": "Team RAP",
            # Known failure fails as expected
            "conclusions": [
                ["success", "http://example.com/run/success"],
                ["success", "http://example.com/run/success"],
                ["success", "http://example.com/run/success"],
                ["failure", "http://example.com/run/fail"],
                ["success", "http://example.com/run/success"],
            ],
        },
        {
            "org": "opensafely",
            "repo": "failing-repo",
            "team": "Team REX",
            # Known failure unexpectedly passes
            "conclusions": [
                ["failure", "http://example.com/run/fail"],
                ["failure", "http://example.com/run/fail"],
                ["failure", "http://example.com/run/fail"],
                ["success", "http://example.com/run/success"],
                ["failure", "http://example.com/run/fail"],
            ],
        },
    ]
)
def test_main_show_failed_skipped():
    # Call main for all repos with skipping successful workflows
    # Skip failures that are already known
    args = jobs.get_command_line_parser().parse_args("show --skip-successful".split())

    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {  # Only the Team REX section should appear and all workflows should be present
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Workflows for Team REX",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "<https://github.com/opensafely/failing-repo/actions?query=branch%3Amain|opensafely/failing-repo>: "
                    "<http://example.com/run/success|:large_green_circle:>"
                    f"{'<http://example.com/run/fail|:red_circle:>' * 4}"
                ),
            },
        },
    ]


def test_main_show_invalid_target():
    # Call main with an invalid org
    args = jobs.get_command_line_parser().parse_args(
        "show --target invalid-org".split()
    )
    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "invalid-org was not recognised",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Run `@test_username workflows usage` to see the valid values for `target`.",
            },
        },
    ]


@patch(
    "workspace.workflows.config.CUSTOM_WORKFLOWS_GROUPS",
    {
        "check-links": {
            "header_text": "Link-checking workflows",
            "workflows": {
                "opensafely/documentation": [82728346],
                "ebmdatalab/bennett.ox.ac.uk": [82728346],
                "ebmdatalab/opensafely.org": [82728346],
                "ebmdatalab/team-manual": [82728346],
            },
        }
    },
)
@use_mock_results(
    [
        {
            "org": "opensafely",
            "repo": "documentation",
            "team": "Tech shared",
            "conclusions": [["success", "https://example.com/run/success"]] * 5,
        },
        {
            "org": "ebmdatalab",
            "repo": "team-manual",
            "team": "Tech shared",
            "conclusions": [["failure", "https://example.com/run/fail"]] * 5,
        },
        {
            "org": "ebmdatalab",
            "repo": "bennett.ox.ac.uk",
            "team": "Tech shared",
            "conclusions": [["success", "https://example.com/run/success"]] * 5,
        },
        {
            "org": "ebmdatalab",
            "repo": "opensafely.org",
            "team": "Tech shared",
            "conclusions": [["failure", "https://example.com/run/fail"]] * 5,
        },
    ]
)
def test_show_group():
    args = jobs.get_command_line_parser().parse_args("show --group check-links".split())
    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {  # Only 1 emoji should appear for each repo
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Link-checking workflows",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<https://github.com/opensafely/documentation/actions?query=branch%3Amain|opensafely/documentation>: <https://example.com/run/success|:large_green_circle:>",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<https://github.com/ebmdatalab/bennett.ox.ac.uk/actions?query=branch%3Amain|ebmdatalab/bennett.ox.ac.uk>: <https://example.com/run/success|:large_green_circle:>",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<https://github.com/ebmdatalab/opensafely.org/actions?query=branch%3Amain|ebmdatalab/opensafely.org>: <https://example.com/run/fail|:red_circle:>",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<https://github.com/ebmdatalab/team-manual/actions?query=branch%3Amain|ebmdatalab/team-manual>: <https://example.com/run/fail|:red_circle:>",
            },
        },
    ]


@patch(
    "workspace.workflows.config.CUSTOM_WORKFLOWS_GROUPS",
    {"check-links": ...},
)
def test_show_group_not_found():
    args = jobs.get_command_line_parser().parse_args("show --group unknown".split())
    blocks = json.loads(jobs.main(args))
    assert blocks == [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Group unknown was not defined",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Available custom workflow groups are: check-links",
            },
        },
    ]
