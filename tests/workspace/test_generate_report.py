import json
from unittest.mock import MagicMock, patch

import pytest

from workspace.report import generate_report


@pytest.fixture(autouse=True)
def reset_github_client_cache():
    """`generate_report.github_client` is a module-level singleton; clear its
    per-org client cache before and after each test so a real `client_for_org`
    call in one test can't leak a cached client into another.
    """
    generate_report.github_client._github_clients = {}
    yield
    generate_report.github_client._github_clients = {}


@pytest.fixture
def mock_org_client(monkeypatch):
    """Stub out installation-token fetching: `client_for_org` always returns
    the same mock client, so tests can exercise `main()` without hitting the
    installation-token endpoint.
    """
    client = MagicMock()
    monkeypatch.setattr(
        generate_report.github_client, "client_for_org", lambda org: client
    )
    return client


def test_github_client_requests_organization_projects_permission():
    assert generate_report.github_client.permissions == {
        "organization_projects": "read"
    }


def test_main_uses_client_for_configured_org():
    # Exercises the real `client_for_org` (unlike `mock_org_client`), to check
    # it routes to the "opensafely-core" org's installation and requests the
    # module's permissions.
    fake_client = MagicMock()
    fake_client.post_graphql.return_value = {
        "data": {
            "organization": {"projectV2": {"id": 1}},
            "node": {
                "items": {
                    "nodes": [],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            },
        }
    }
    with patch(
        "workspace.utils.github_rest_api.github_client_for_org",
        return_value=fake_client,
    ) as mock_github_client_for_org:
        generate_report.main(13, ["Backlog"])
    mock_github_client_for_org.assert_called_once_with(
        123, {"organization_projects": "read"}
    )


def test_generate_report(mock_org_client):
    mock_org_client.post_graphql.return_value = {
        "data": {
            "organization": {"projectV2": {"id": 1}},
            "node": {
                "items": {
                    "nodes": [
                        {
                            "content": {
                                "title": "Card 1",
                                "bodyUrl": "http://card1",
                                "assignees": {"nodes": []},
                            },
                            "fieldValues": {
                                "nodes": [
                                    {},
                                    {
                                        "name": "Under Review",
                                        "field": {"name": "Status"},
                                    },
                                ]
                            },
                        },
                        {
                            "content": {
                                "title": "Card 2",
                                "assignees": {"nodes": []},
                            },
                            "fieldValues": {
                                "nodes": [
                                    {
                                        "name": "In Progress",
                                        "field": {"name": "Status"},
                                    },
                                    {},
                                ]
                            },
                        },
                        {
                            "content": {
                                "title": "Card 3",
                                "assignees": {"nodes": []},
                            },
                            "fieldValues": {
                                "nodes": [
                                    {
                                        "name": "Blocked",
                                        "field": {"name": "Status"},
                                    }
                                ]
                            },
                        },
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": "abc"},
                }
            },
        }
    }
    response = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":newspaper: Project Board Summary :newspaper:",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<https://github.com/orgs/opensafely-core/projects/13/views/1|View board>",
            },
        },
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Under Review*"}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\u2022 <http://card1|Card 1>\n"},
        },
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Blocked*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\u2022 Card 3\n"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*In Progress*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\u2022 Card 2\n"}},
    ]

    statuses = ["Under Review", "Blocked", "In Progress"]
    assert generate_report.main(13, statuses) == json.dumps(response)


def test_generate_report_with_custom_org(mock_org_client):
    def fake_post_graphql(query, variables):
        # Verify the org parameter is passed to the query
        assert variables["org_name"] == "custom-org"
        return {
            "data": {
                "organization": {"projectV2": {"id": 1}},
                "node": {
                    "items": {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": False, "endCursor": "abc"},
                    }
                },
            }
        }

    mock_org_client.post_graphql.side_effect = fake_post_graphql

    response = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":newspaper: Project Board Summary :newspaper:",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<https://github.com/orgs/custom-org/projects/99/views/1|View board>",
            },
        },
    ]

    assert generate_report.main(99, ["Backlog"], org="custom-org") == json.dumps(
        response
    )


def test_generate_report_no_issues(mock_org_client):
    mock_org_client.post_graphql.return_value = {
        "data": {
            "organization": {"projectV2": {"id": 1}},
            "node": {
                "items": {
                    "nodes": "",
                    "pageInfo": {"hasNextPage": False, "endCursor": "abc"},
                }
            },
        }
    }

    response = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":newspaper: Project Board Summary :newspaper:",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<https://github.com/orgs/opensafely-core/projects/13/views/1|View board>",
            },
        },
    ]

    statuses = ["Under Review", "Blocked", "In Progress"]
    assert generate_report.main(13, statuses) == json.dumps(response)
