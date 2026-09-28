import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from workspace.utils import github_rest_api


WORKSPACE = Path("workspace")

WRITE_METHOD_PATTERN = re.compile(r"\brequests\.(post|put|patch|delete)\b")


def test_no_write_http_calls_in_workspace():
    """Workspace jobs that call the GitHub API should be read-only; any write would
    have to bypass workspace/utils/github_rest_api.py, which enforces GET calls only
    (with the exception of fetching access tokens and GraphQL calls (see
    `GitHubAPIClient.post_graphql`). Everything that talks to GitHub (REST or GraphQL)
    goes through that module now, so no file should call `requests` directly.
    Note that this will fail on non-GET request to ANY url, not just github, but that's
    ok for now.
    """
    offenders = []
    for path in WORKSPACE.rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if WRITE_METHOD_PATTERN.search(line):  # pragma: no cover
                # Only reachable when something is broken; we'd assert below.
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Found non-GET requests calls in workspace/. If this is a GitHub REST API "
        "call, it should be read-only and go through workspace/utils/github_rest_api.py."
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete", "head"])
def test_read_only_session_rejects_non_get(method):
    session = github_rest_api.ReadOnlySession()
    with pytest.raises(RuntimeError, match="read-only"):
        getattr(session, method)("https://api.github.com/anything")


def test_read_only_session_allows_access_token_post():
    with patch.object(github_rest_api.requests.Session, "request"):
        session = github_rest_api.ReadOnlySession()
        # this is fine
        session.post("https://api.github.com/app/installations/123/access_tokens/")
        # so is the trailing slash
        session.post("https://api.github.com/app/installations/123/access_tokens")
        # this doesn't match
        with pytest.raises(RuntimeError, match="read-only"):
            session.post("https://api.github.com/app/installations/foo/access_tokens")


def test_read_only_session_allows_graphql_post():
    with patch.object(github_rest_api.requests.Session, "request"):
        session = github_rest_api.ReadOnlySession()
        # this is fine
        session.post("https://api.github.com/graphql")
        # this doesn't match - only the exact GraphQL URL is allowed
        with pytest.raises(RuntimeError, match="read-only"):
            session.post("https://api.github.com/graphql/anything")


def test_post_graphql_sends_query_and_variables():
    client = github_rest_api.GitHubAPIClient("test-token", api_version="2024-01-01")
    response = MagicMock()
    with patch.object(
        github_rest_api.readonly_session, "post", return_value=response
    ) as mock_post:
        client.post_graphql("query { viewer { login } }", {"foo": "bar"})
    mock_post.assert_called_once_with(
        "https://api.github.com/graphql",
        headers={
            "Authorization": "Bearer test-token",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bennettbot",
            "X-GitHub-Api-Version": "2024-01-01",
            "GraphQL-Features": "projects_next_graphql",
        },
        json={"query": "query { viewer { login } }", "variables": {"foo": "bar"}},
    )


@pytest.mark.parametrize(
    "query",
    [
        "mutation { addComment(input: {}) { clientMutationId } }",
        "mutation UpdateThing($id: ID!) { updateThing(id: $id) { id } }",
        "  mutation { addComment(input: {}) { clientMutationId } }",
    ],
)
def test_post_graphql_rejects_mutation(query):
    client = github_rest_api.GitHubAPIClient("test-token")
    with patch.object(github_rest_api.readonly_session, "post") as mock_post:
        with pytest.raises(RuntimeError, match="read-only"):
            client.post_graphql(query)
    mock_post.assert_not_called()


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
        status_code=200,
        links={"next": {"url": "https://api.github.com/page2"}},
        headers={},
    )
    page1.json.return_value = {"codespaces": [{"name": "a"}, {"name": "b"}]}
    page2 = MagicMock(status_code=200, links={}, headers={})
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
    page1 = MagicMock(
        status_code=200,
        links={"next": {"url": "https://api.github.com/page2"}},
        headers={},
    )
    page1.json.return_value = [1, 2, 3]
    page2 = MagicMock(status_code=200, links={}, headers={})
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
    # The second call is a positional-only invocation of `_session.get(next_url,
    # headers=…)` so it has no `params` kwarg.
    assert "params" not in mock_get.call_args_list[1].kwargs


def test_get_paginated_json_exposes_first_page_etag():
    client = github_rest_api.GitHubAPIClient("test-token")
    response = MagicMock(status_code=200, links={}, headers={"ETag": "p1-etag"})
    response.json.return_value = [1, 2]
    with patch.object(github_rest_api.readonly_session, "get", return_value=response):
        result = client.get_paginated_json("https://api.github.com/x")
    assert result.etag == "p1-etag"
    assert not result.not_modified
    assert list(result) == [1, 2]


def test_get_paginated_json_with_etag_returns_not_modified_on_304():
    client = github_rest_api.GitHubAPIClient("test-token")
    response = MagicMock(status_code=304)
    with patch.object(
        github_rest_api.readonly_session, "get", return_value=response
    ) as mock_get:
        result = client.get_paginated_json("https://api.github.com/x", etag="old-etag")
    assert result.not_modified
    assert result.etag == "old-etag"
    assert list(result) == []
    assert mock_get.call_args.kwargs["headers"]["If-None-Match"] == "old-etag"


@pytest.mark.parametrize(
    "expiry,expected",
    [
        (datetime(2026, 3, 1, 10, 30, 30, tzinfo=UTC), 30),
        (datetime(2026, 3, 1, 10, 29, 30, tzinfo=UTC), -30),
        (None, None),
    ],
)
def test_client_with_token_expiry(freezer, expiry, expected):
    freezer.move_to(datetime(2026, 3, 1, 10, 30, 0, tzinfo=UTC))
    client = github_rest_api.GitHubAPIClient("test-token", expiry=expiry)
    assert client.seconds_to_token_expiry() == expected


@patch("workspace.utils.github_rest_api.jwt.encode")
def test_get_jwt(mock_encode, freezer):
    mock_now = datetime(2026, 3, 1, 10, 30, 0, tzinfo=UTC)
    freezer.move_to(mock_now)
    ts = mock_now.timestamp()
    github_rest_api.get_jwt()
    mock_encode.assert_called_with(
        {"iat": ts, "exp": ts + 300, "iss": "client-id"},
        "private-key",
        algorithm="RS256",
    )


def test_get_installation_token():
    response = MagicMock(links={})
    response.json.return_value = {
        "token": "installation-token",
        "expires_at": "2026-03-01T11:30:00+00:00",
    }
    with patch.object(
        github_rest_api.readonly_session, "post", return_value=response
    ) as mock_post:
        token, expiry = github_rest_api.get_installation_token(
            123, "test-jwt", {"metadata": "read"}
        )
    assert token == "installation-token"
    assert expiry == datetime(2026, 3, 1, 11, 30, tzinfo=UTC)
    mock_post.assert_called_once_with(
        "https://api.github.com/app/installations/123/access_tokens",
        headers={
            "Authorization": "Bearer test-jwt",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bennettbot",
            "X-GitHub-Api-Version": "2026-03-10",
        },
        json={"permissions": {"metadata": "read"}},
    )


def test_create_github_client_for_org():
    with (
        patch.object(
            github_rest_api, "get_jwt", return_value="test-jwt"
        ) as mock_get_jwt,
        patch.object(
            github_rest_api,
            "get_installation_token",
            return_value=(
                "installation-token",
                datetime(2026, 3, 1, 11, 30, tzinfo=UTC),
            ),
        ) as mock_get_token,
    ):
        client = github_rest_api.create_github_client_for_org(123, {"metadata": "read"})
    mock_get_jwt.assert_called_once()
    mock_get_token.assert_called_once_with(123, "test-jwt", {"metadata": "read"})
    assert isinstance(client, github_rest_api.GitHubAPIClient)
    assert client.headers["Authorization"] == "Bearer installation-token"
    assert client.expiry == datetime(2026, 3, 1, 11, 30, tzinfo=UTC)


def test_get_client_for_org_default_permissions():
    org_client = MagicMock(seconds_to_token_expiry=lambda: 3600)
    with patch.object(
        github_rest_api, "create_github_client_for_org", return_value=org_client
    ) as mock_client_for_org:
        github_rest_api.get_client_for_org("opensafely-core")
    mock_client_for_org.assert_called_once_with(123, {"metadata": "read"})


def test_get_client_for_org_creates_and_caches_client():
    org_client = MagicMock(seconds_to_token_expiry=lambda: 3600)
    with patch.object(
        github_rest_api, "create_github_client_for_org", return_value=org_client
    ) as mock_client_for_org:
        result = github_rest_api.get_client_for_org(
            "opensafely-core", {"metadata": "read"}
        )
        assert result is org_client
        mock_client_for_org.assert_called_once_with(123, {"metadata": "read"})

        # A second call with the same org and permissions reuses the cached
        # client rather than fetching a new installation token.
        refetched_client = github_rest_api.get_client_for_org(
            "opensafely-core", {"metadata": "read"}
        )
    assert refetched_client is org_client
    mock_client_for_org.assert_called_once()


def test_get_client_for_org_cache_ignores_permissions_key_order():
    # The cache key sorts permissions items, so a dict with the same
    # key/value pairs in a different order still hits the same cache
    # entry rather than creating a redundant installation token.
    org_client = MagicMock(seconds_to_token_expiry=lambda: 3600)
    with patch.object(
        github_rest_api, "create_github_client_for_org", return_value=org_client
    ) as mock_client_for_org:
        first = github_rest_api.get_client_for_org(
            "opensafely-core", {"metadata": "read", "contents": "read"}
        )
        second = github_rest_api.get_client_for_org(
            "opensafely-core", {"contents": "read", "metadata": "read"}
        )
    assert first is org_client
    assert second is org_client
    mock_client_for_org.assert_called_once()


def test_get_client_for_org_regenerates_expiring_token():
    stale_client = MagicMock(seconds_to_token_expiry=lambda: 60)
    fresh_client = MagicMock(seconds_to_token_expiry=lambda: 3600)
    with patch.object(
        github_rest_api,
        "create_github_client_for_org",
        side_effect=[stale_client, fresh_client],
    ) as mock_client_for_org:
        first = github_rest_api.get_client_for_org(
            "opensafely-core", {"metadata": "read"}
        )
        second = github_rest_api.get_client_for_org(
            "opensafely-core", {"metadata": "read"}
        )
    assert first is stale_client
    assert second is fresh_client
    assert mock_client_for_org.call_count == 2


def test_get_client_for_org_uses_separate_clients_per_org():
    core_client = MagicMock(seconds_to_token_expiry=lambda: 3600)
    ebm_client = MagicMock(seconds_to_token_expiry=lambda: 3600)
    with patch.object(
        github_rest_api,
        "create_github_client_for_org",
        side_effect=[core_client, ebm_client],
    ) as mock_client_for_org:
        assert (
            github_rest_api.get_client_for_org("opensafely-core", {"metadata": "read"})
            is core_client
        )
        assert (
            github_rest_api.get_client_for_org("ebmdatalab", {"metadata": "read"})
            is ebm_client
        )
    mock_client_for_org.assert_any_call(123, {"metadata": "read"})
    mock_client_for_org.assert_any_call(456, {"metadata": "read"})


def test_get_client_for_org_uses_separate_clients_per_permissions():
    # Same org with different permissions must not share a cached client
    metadata_client = MagicMock(seconds_to_token_expiry=lambda: 3600)
    contents_client = MagicMock(seconds_to_token_expiry=lambda: 3600)
    with patch.object(
        github_rest_api,
        "create_github_client_for_org",
        side_effect=[metadata_client, contents_client],
    ) as mock_client_for_org:
        assert (
            github_rest_api.get_client_for_org("opensafely-core", {"metadata": "read"})
            is metadata_client
        )
        assert (
            github_rest_api.get_client_for_org("opensafely-core", {"contents": "read"})
            is contents_client
        )
    mock_client_for_org.assert_any_call(123, {"metadata": "read"})
    mock_client_for_org.assert_any_call(123, {"contents": "read"})


def test_get_client_for_org_unknown_org_raises_error():
    # "nonexistent-org" isn't in test repos_config.yaml's installation_ids at all.
    with pytest.raises(
        AssertionError, match="installation id not configured for nonexistent-org"
    ):
        github_rest_api.get_client_for_org("nonexistent-org")


def test_get_client_for_org_configured_but_empty_raises_error():
    # An org can be present in installation_ids but not yet have an app
    # installed for it (a falsy value) - mock this rather than relying on a
    # fixture org in tests/repos_config.yaml, since we otherwise assume every
    # configured org is properly set up.
    with patch.object(
        github_rest_api.repos_config,
        "installation_ids",
        return_value={"some-org": None},
    ):
        with pytest.raises(
            AssertionError, match="installation id not configured for some-org"
        ):
            github_rest_api.get_client_for_org("some-org")


@pytest.mark.parametrize(
    "org, env_var",
    [
        # - replaced with _ in env var
        ("my-org", "MY_ORG_DEV_GITHUB_TOKEN"),
        ("anotherorg", "ANOTHERORG_DEV_GITHUB_TOKEN"),
    ],
)
def test_get_client_for_org_uses_dev_token_when_app_credentials_missing(
    monkeypatch, org, env_var
):
    # No GITHUB_APP_CLIENT_ID/GITHUB_APP_PRIVATE_KEY, so get_client_for_org falls
    # back to a dev PAT from env, without requesting a real installation token.
    monkeypatch.delenv("GITHUB_APP_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.setenv(env_var, "dev-pat-token")
    with patch.object(
        github_rest_api, "create_github_client_for_org"
    ) as mock_github_client_for_org:
        client = github_rest_api.get_client_for_org(org)
    mock_github_client_for_org.assert_not_called()
    assert client.headers["Authorization"] == "Bearer dev-pat-token"


def test_get_client_for_org_partial_app_credentials_falls_back_to_dev_token(
    monkeypatch,
):
    # Both GITHUB_APP_ env vars are required
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("MY_ORG_DEV_GITHUB_TOKEN", "dev-pat-token")
    client = github_rest_api.get_client_for_org("my-org")
    assert client.headers["Authorization"] == "Bearer dev-pat-token"


def test_get_client_for_org_dev_fallback_missing_token_raises(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("MY_ORG_DEV_GITHUB_TOKEN", raising=False)
    with pytest.raises(
        AssertionError,
        match="no local-dev fallback token was found in MY_ORG_DEV_GITHUB_TOKEN",
    ):
        github_rest_api.get_client_for_org("my-org")
