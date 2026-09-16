import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from workspace.codespaces import codespaces


@pytest.fixture(autouse=True)
def reset_github_client_cache():
    """`codespaces.github_client` is a module-level singleton; clear its
    per-org client cache before and after each test so a real `client_for_org`
    call in one test can't leak a cached client into another.
    """
    codespaces.github_client._github_clients = {}
    yield
    codespaces.github_client._github_clients = {}


@pytest.fixture
def mock_org_client(monkeypatch):
    """Stub out installation-token fetching: `client_for_org` always returns
    the same mock client, so tests can exercise `main()` without hitting the
    installation-token endpoint.
    """
    client = MagicMock()
    monkeypatch.setattr(codespaces.github_client, "client_for_org", lambda org: client)
    return client


def make_record(
    owner="alice",
    name="cs-1",
    repo="study-repo",
    retention_expires_at="2026-01-20T10:00:00+00:00",
    retention_period_minutes=30 * 24 * 60,
    has_uncommitted=True,
    has_unpushed=False,
):
    return {
        "owner": {"login": owner},
        "name": name,
        "repository": {"name": repo},
        "retention_expires_at": retention_expires_at,
        "retention_period_minutes": retention_period_minutes,
        "git_status": {
            "has_uncommitted_changes": has_uncommitted,
            "has_unpushed_changes": has_unpushed,
        },
    }


def test_get_codespace_extracts_fields(freezer):
    freezer.move_to("2026-01-15T10:00:00+00:00")
    cs = codespaces.get_codespace(make_record())
    assert cs == codespaces.Codespace(
        owner="alice",
        name="cs-1",
        repo="study-repo",
        retention_expires_at=datetime(2026, 1, 20, 10, 0, tzinfo=UTC),
        remaining_retention_period_days=5,
        retention_period_days=30,
        has_uncommitted=True,
        has_unpushed=False,
    )


def test_get_codespace_no_retention_expiry(freezer):
    freezer.move_to("2026-01-15T10:00:00+00:00")
    cs = codespaces.get_codespace(make_record(retention_expires_at=None))
    assert cs.retention_expires_at is None
    assert cs.remaining_retention_period_days is None


def test_get_codespace_no_retention_period_minutes(freezer):
    freezer.move_to("2026-01-15T10:00:00+00:00")
    cs = codespaces.get_codespace(make_record(retention_period_minutes=None))
    assert cs.retention_period_days is None


@pytest.mark.parametrize(
    "remaining_days, threshold, has_uncommitted, has_unpushed, expected",
    [
        (5, 5, True, False, True),  # at the threshold, uncommitted changes
        (5, 5, False, True, True),  # at the threshold, unpushed changes
        (6, 5, True, True, False),  # beyond the threshold
        (5, 5, False, False, False),  # within threshold but no unsaved changes
        (None, 5, True, True, False),  # kept indefinitely, so never at risk
    ],
)
def test_is_at_risk(remaining_days, threshold, has_uncommitted, has_unpushed, expected):
    cs = codespaces.Codespace(
        owner="alice",
        name="cs-1",
        repo="study-repo",
        retention_expires_at=None,
        remaining_retention_period_days=remaining_days,
        retention_period_days=30,
        has_uncommitted=has_uncommitted,
        has_unpushed=has_unpushed,
    )
    assert codespaces.is_at_risk(cs, threshold) is expected


def test_github_client_requests_organization_codespaces_permission():
    assert codespaces.github_client.permissions == {
        "organization_codespaces": "read",
        "codespaces": "read",
    }


def test_main_uses_client_for_configured_org():
    # Exercises the real `client_for_org` (unlike `mock_org_client`), to check
    # it routes to the "opensafely" org's installation and requests the
    # module's permissions/api_version.
    fake_client = MagicMock()
    fake_client.get_paginated_json.return_value = []
    with patch(
        "workspace.utils.github_rest_api.github_client_for_org",
        return_value=fake_client,
    ) as mock_github_client_for_org:
        codespaces.main(5)
    mock_github_client_for_org.assert_called_once_with(
        789, {"organization_codespaces": "read", "codespaces": "read"}
    )


def test_main_reports_at_risk_codespaces(mock_org_client, freezer):
    freezer.move_to("2026-01-15T10:00:00+00:00")
    at_risk_soon = make_record(
        owner="alice",
        name="cs-soon",
        repo="study-repo",
        retention_expires_at="2026-01-15T10:00:01+00:00",  # <1 day remaining
        has_uncommitted=True,
        has_unpushed=True,
    )
    at_risk_later = make_record(
        owner="bob",
        name="cs-later",
        repo="study-repo",
        retention_expires_at="2026-01-20T10:00:00+00:00",  # 5 days remaining
        has_uncommitted=True,
        has_unpushed=False,
    )
    not_at_risk_far_off = make_record(
        owner="carol",
        name="cs-far",
        repo="study-repo",
        retention_expires_at="2026-03-01T10:00:00+00:00",  # well beyond threshold
        has_uncommitted=True,
        has_unpushed=True,
    )
    kept_indefinitely = make_record(
        owner="dave",
        name="cs-forever",
        repo="study-repo",
        retention_expires_at=None,
        retention_period_minutes=None,
        has_uncommitted=True,
        has_unpushed=True,
    )
    excluded = make_record(
        owner="erin",
        name="cs-excluded",
        repo="documentation",  # in the hard-coded excluded_repos list
        retention_expires_at="2026-01-15T10:00:01+00:00",
        has_uncommitted=True,
        has_unpushed=True,
    )
    mock_org_client.get_paginated_json.return_value = [
        at_risk_soon,
        at_risk_later,
        not_at_risk_far_off,
        kept_indefinitely,
        excluded,
    ]

    blocks = json.loads(codespaces.main(threshold_in_days=5))
    rendered = json.dumps(blocks)

    assert "cs-soon" in rendered
    assert "cs-later" in rendered
    assert "cs-far" not in rendered
    assert "cs-forever" not in rendered
    assert "cs-excluded" not in rendered
    # Soonest-expiring at-risk codespace is listed first.
    assert rendered.index("cs-soon") < rendered.index("cs-later")
    assert "<1 day" in rendered
    assert "5 days" in rendered
    assert "Yes" in rendered
    assert "No" in rendered


def test_main_no_at_risk_codespaces(mock_org_client):
    mock_org_client.get_paginated_json.return_value = []
    blocks = json.loads(codespaces.main(threshold_in_days=5))
    rendered = json.dumps(blocks)
    assert "tada" in rendered
