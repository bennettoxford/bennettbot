"""Shared, read-only GitHub REST client.

Each workspace job that needs to talk to the GitHub API instantiates a
`GitHubAPIClient` with its own token (different namespaces use different
tokens with different scopes). All clients share a single read-only
`requests.Session` underneath, which refuses any non-GET HTTP method.
"""

import requests


class ReadOnlySession(requests.Session):
    """A `requests.Session` that refuses any non-GET HTTP method.

    A basic guard against accidentally writing to GitHub via this module.
    Tokens may have scopes that permit writes (classic PATs can't be
    narrowed to read-only), so this session enforces read-only at the
    request layer: any future code that calls .post()/.put()/etc. through
    `readonly_session` will raise an error.
    """

    def request(self, method, url, *args, **kwargs):
        if method.upper() != "GET":
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

    Parameters:
        token: the GitHub PAT (classic or fine-grained) or installation
            token to authenticate with. The required scopes are
            endpoint-specific; see each caller's notes for what's needed.
        api_version: value for the `X-GitHub-Api-Version` header. Pin
            this so a future GitHub default bump can't silently change
            response shapes. Override per client when an endpoint expects
            an older version.
    """

    # Headers other than Authorization follow GitHub's REST recommendations:
    #  - `Accept` pins the response media type
    #  - `User-Agent` identifies us in GitHub's logs (required by GitHub;
    #    although the requests library's default would technically pass)
    def __init__(self, token: str, api_version: str = "2026-03-10"):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bennettbot",
            "X-GitHub-Api-Version": api_version,
        }

    def get_json(self, url: str, params: dict | None = None) -> dict | list:
        """Single GET, returning the JSON body."""
        response = readonly_session.get(url, headers=self.headers, params=params)
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
