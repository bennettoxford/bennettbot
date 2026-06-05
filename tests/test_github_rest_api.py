import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from workspace.utils import github_rest_api


WORKSPACE = Path("workspace")

# Files in workspace/ allowed to make POST requests
# We expect that jobs will only make GET requests (enforced by github_rest_api.py
# for GitHub REST requests).
# Some jobs may legitimately need to; currently that's only the reports which
# use the GraphQL API to make reads that go via POST.
# We could do complicated things to report only on request to github.com, but
# since nothing else needs to POST (or do any other non-GET method) atm, we just mark
# the specific files that can be excluded from the check. In future we might want to
# make this exclusion more targeted, but this is sufficient for now.
ALL_METHODS_ALLOWED = {
    Path("workspace/report/generate_report.py"),
}

WRITE_METHOD_PATTERN = re.compile(r"\brequests\.(post|put|patch|delete)\b")


def test_no_write_http_calls_in_workspace():
    """Workspace jobs that call the GitHub API should be read-only; any write would
    have to bypass workspace/utils/github_rest_api.py, which enforces GET calls only.
    Fail if workspace file invokes a non-GET requests method, except those explicitly
    allowlisted for read-only POSTs (e.g. GraphQL queries). Note that this will fail
    on non-GET request to ANY url, not just github, but that's ok for now.
    """
    offenders = []
    for path in WORKSPACE.rglob("*.py"):
        if path in ALL_METHODS_ALLOWED:
            # allow any method for this path
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if WRITE_METHOD_PATTERN.search(line):  # pragma: no cover
                # Only reachable when something is broken; we'd assert below.
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Found non-GET requests calls in workspace/. If this is a GitHub REST API"
        "call, it should be read-only and go through workspace/utils/github_rest_api.py.\n"
        "If this file should legitimately be using non-GET calls, add it to POST_ALLOWED."
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete", "head"])
def test_read_only_session_rejects_non_get(method):
    session = github_rest_api.ReadOnlySession()
    with pytest.raises(RuntimeError, match="read-only"):
        getattr(session, method)("https://api.github.com/anything")


def test_client_sends_expected_headers():
    client = github_rest_api.GitHubAPIClient("test-token", api_version="2024-01-01")
    response = MagicMock(links={})
    response.json.return_value = {"ok": True}
    with patch.object(
        github_rest_api.readonly_session, "get", return_value=response
    ) as mock_get:
        client.get_json("https://api.github.com/example")
    assert mock_get.call_args.kwargs["headers"] == {
        "Authorization": "Bearer test-token",
        "Accept": "application/vnd.github+json",
        "User-Agent": "bennettbot",
        "X-GitHub-Api-Version": "2024-01-01",
    }


def test_get_paginated_json_with_results_key_unwraps_pages():
    client = github_rest_api.GitHubAPIClient("test-token")
    page1 = MagicMock(
        links={"next": {"url": "https://api.github.com/page2"}},
    )
    page1.json.return_value = {"codespaces": [{"name": "a"}, {"name": "b"}]}
    page2 = MagicMock(links={})
    page2.json.return_value = {"codespaces": [{"name": "c"}]}
    with patch.object(
        github_rest_api.readonly_session, "get", side_effect=[page1, page2]
    ):
        results = list(
            client.get_paginated_json(
                "https://api.github.com/page1", results_key="codespaces"
            )
        )
    assert results == [{"name": "a"}, {"name": "b"}, {"name": "c"}]


def test_get_paginated_json_follows_link_header_and_passes_params_once():
    client = github_rest_api.GitHubAPIClient("test-token")
    page1 = MagicMock(links={"next": {"url": "https://api.github.com/page2"}})
    page1.json.return_value = [1, 2, 3]
    page2 = MagicMock(links={})
    page2.json.return_value = [4, 5]
    with patch.object(
        github_rest_api.readonly_session, "get", side_effect=[page1, page2]
    ) as mock_get:
        results = list(
            client.get_paginated_json(
                "https://api.github.com/page1", params={"foo": "bar"}
            )
        )
    assert results == [1, 2, 3, 4, 5]
    # The Link-header URL already encodes the original query string, so subsequent
    # pages must not re-send the caller's params.
    assert mock_get.call_args_list[0].kwargs["params"] == {"foo": "bar"}
    assert mock_get.call_args_list[1].kwargs["params"] is None
