"""Shared, read-only GitHub REST client.

Each workspace job that needs to talk to the GitHub API instantiates a
`GitHubAPIClient` with its own token (different namespaces use different
tokens with different scopes). All clients share a single read-only
`requests.Session` underneath, which refuses any non-GET HTTP method.
"""

import os
import re
import time
from datetime import UTC, datetime

import jwt
import requests

from workspace.utils import repos_config


GRAPHQL_URL = "https://api.github.com/graphql"


class ReadOnlySession(requests.Session):
    """A `requests.Session` that refuses any non-GET HTTP method, with the
    exception of calls to fetch an app installation token and GraphQL queries.

    A basic guard against accidentally writing to GitHub via this module.
    Tokens may have scopes that permit writes (classic PATs can't be
    narrowed to read-only), so this session enforces read-only at the
    request layer: any future code that calls .post()/.put()/etc. through
    `readonly_session` will raise an error.

    Note that we're now using a GitHub app with readonly permissions, but
    we keep the guard anyway.

    GraphQL has no GET equivalent - it's a single POST endpoint - so it's
    allowed through as an exception too (see `GitHubAPIClient.post_graphql`).
    """

    access_token_re = re.compile(
        r"https://api\.github\.com/app/installations/\d+/access_tokens/?"
    )

    def request(self, method, url, *args, **kwargs):
        allowed = (
            method.upper() == "GET"
            or url == GRAPHQL_URL
            or self.access_token_re.match(url)
        )
        if not allowed:
            raise RuntimeError(
                f"workspace.utils.github_rest_api is read-only; refusing {method!r} "
                f"request to {url}."
            )
        return super().request(method, url, *args, **kwargs)


# Single session shared by all clients - it has no per-token state (auth
# headers are passed per-request), so sharing the underlying connection pool
# is safe and tests can patch one location to intercept any client's calls.
readonly_session = ReadOnlySession()


class GitHubAPIClient:
    """Read-only client for the GitHub REST API.

    Allows a single POST, to get app installation tokens.

    Parameters:
        token: the GitHub PAT (classic or fine-grained) or installation
            token to authenticate with. The required scopes or permissions
            are endpoint-specific; see each caller's notes for what's needed.
        expiry: token expiry datetime
        api_version: value for the `X-GitHub-Api-Version` header. Pin
            this so a future GitHub default bump can't silently change
            response shapes. Override per client when an endpoint expects
            an older version.
    """

    # Headers other than Authorization follow GitHub's REST recommendations:
    #  - `Accept` pins the response media type
    #  - `User-Agent` identifies us in GitHub's logs (required by GitHub;
    #    although the requests library's default would technically pass)
    def __init__(
        self,
        token: str,
        expiry: datetime | None = None,
        api_version: str = "2026-03-10",
    ):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bennettbot",
            "X-GitHub-Api-Version": api_version,
        }
        self.expiry = expiry

    def seconds_to_token_expiry(self):
        if self.expiry:
            return (self.expiry - datetime.now(tz=UTC)).total_seconds()

    def get_json(self, url: str, params: dict | None = None) -> dict | list:
        """Single GET, returning the JSON body."""
        response = readonly_session.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def post_json(self, url: str, params: dict | None = None) -> dict | list:
        """Single POST, returning the JSON body."""
        response = readonly_session.post(url, headers=self.headers, json=params)
        response.raise_for_status()
        return response.json()

    # Prevent "mutation" queries; note that we don't just allow the `query`
    # keyword (although all our current queries use it), because GraphQL allows an
    # the `query` keyword to be omitted entirely, and there are other non-mutating
    # operation types. We just prevent "mutation", which is the only keyword that writes,
    mutation_re = re.compile(r"^\s*mutation\b")

    def post_graphql(self, query: str, variables: dict | None = None) -> dict:
        """POST a GraphQL query, returning the parsed JSON body.

        The GitHub GraphQL API is a single POST endpoint - there's no GET
        equivalent - so `ReadOnlySession` allows this URL through as an
        exception but refuses to send a mutation operation.
        """
        if self.mutation_re.match(query):
            raise RuntimeError(
                "workspace.utils.github_rest_api is read-only; refusing a GraphQL "
                "mutation."
            )
        headers = {**self.headers, "GraphQL-Features": "projects_next_graphql"}
        response = readonly_session.post(
            GRAPHQL_URL,
            headers=headers,
            json={"query": query, "variables": variables},
        )
        response.raise_for_status()
        return response.json()

    def get_paginated_json(
        self,
        url: str,
        params: dict | None = None,
        etag: str | None = None,
        results_key: str | None = None,
    ) -> "PagedResponse":
        """Fetch records across all pages, following the "next" Link header.

        Returns a `PagedResponse` - an iterable that yields records lazily
        (subsequent pages aren't fetched until consumed).

        Optionally, pass an etag from a previous response to send
        `If-None-Match` headers so callers can cache and reuse data.
        Callers that don't care about caching can just iterate the result
        and ignore etag/not_modified entirely.

        Note: the ETag tracks the first page only. This
        is reliable for endpoints where any change bubbles up to page 1
        (e.g. lists sorted by created/updated desc), but for endpoints where
        changes may be on subsequent pages only, alternative forms of caching
        will be required.

        For endpoints whose JSON body is a bare array (e.g. Dependabot
        alerts), leave `results_key` as None. For endpoints that wrap the
        array under a key (e.g. `{"codespaces": [...]}`), pass that key
        so the helper can unwrap each page.
        """
        headers = dict(self.headers)
        if etag is not None:
            headers["If-None-Match"] = etag

        # Fetch page 1 eagerly so the caller can read etag/not_modified before
        # deciding whether to iterate.
        response = readonly_session.get(url, headers=headers, params=params)
        if response.status_code == 304:
            return PagedResponse(records=iter(()), etag=etag, not_modified=True)
        response.raise_for_status()

        return PagedResponse(
            records=self._walk_pages(response, results_key),
            etag=response.headers.get("ETag"),
        )

    def _walk_pages(self, response, results_key):
        """Yield records from `response`, then follow Link rel='next' pages."""
        while True:
            page = response.json()
            if results_key is not None:
                page = page[results_key]
            yield from page
            # The Link-header URL already includes the original query string,
            # so subsequent calls send no extra params.
            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return
            response = readonly_session.get(next_url, headers=self.headers)
            response.raise_for_status()


class PagedResponse:
    """Iterable wrapper around the result of `GitHubAPIClient.get_paginated_json`.

    Iterating yields each record across all pages (subsequent pages fetched
    lazily). The first page's `ETag` is exposed for callers that want to
    cache and send `If-None-Match` next time; `not_modified` is True when
    the caller passed an `etag` that the server accepted (HTTP 304), in
    which case iteration yields nothing.
    """

    def __init__(self, records, etag, not_modified=False):
        self._records = records
        self.etag = etag
        self.not_modified = not_modified

    def __iter__(self):
        return iter(self._records)


def get_jwt():
    signing_key = os.environ["GITHUB_APP_PRIVATE_KEY"]
    payload = {
        # Issued at time
        "iat": int(time.time()),
        # JWT expiration time (5 minutes)
        "exp": int(time.time()) + 300,
        # GitHub App's client ID
        "iss": os.environ["GITHUB_APP_CLIENT_ID"],
    }

    # Create JWT
    return jwt.encode(payload, signing_key, algorithm="RS256")


def get_installation_token(installation_id: int, jwt: str, permissions: dict[str, str]):
    client = GitHubAPIClient(token=jwt)
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    resp = client.post_json(url, params={"permissions": permissions})
    return resp["token"], datetime.fromisoformat(resp["expires_at"])


def github_client_for_org(installation_id: int, permissions: dict[str, str]):
    token, expiry = get_installation_token(installation_id, get_jwt(), permissions)
    return GitHubAPIClient(token, expiry)


class GitHubMultiOrgClient:
    """
    A wrapper for multiple github clients per organisation, each with its
    own app installation token and restricted set of permissions.

    If no permissions are supplied, default to the minumim {metadata: read}
    (passing an empty dict as permissions gives us a token with all the
    app's permissions)

    Clients are created, with their tokens, only when required; app installation
    tokens expire in 1 hour, so when a caller retrieves a client for a particular org,
    we check it's not expiring in the next 10 minutes, and regenerate it if required.
    """

    max_token_age_seconds = 10 * 60

    def __init__(self, permissions: dict[str, str] | None = None):
        self._github_clients = {}
        self.permissions = permissions or {"metadata": "read"}

    def client_for_org(self, org):
        client = self._github_clients.get(org)
        if (
            client is None
            or client.seconds_to_token_expiry() < self.max_token_age_seconds
        ):
            installation_ids = repos_config.installation_ids()
            assert org in installation_ids, f"installation id not configured for {org}"
            installation_id = repos_config.installation_ids()[org]
            self._github_clients[org] = github_client_for_org(
                installation_id, self.permissions
            )
        return self._github_clients[org]
