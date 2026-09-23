import json
from unittest.mock import MagicMock, patch

import pytest

from workspace.report import generate_report


@pytest.fixture
def mock_org_client(monkeypatch):
    """Stub out installation-token fetching: `get_client_for_org` always
    returns the same mock client, so tests can exercise `main()` without
    hitting the installation-token endpoint.
    """
    client = MagicMock()
    monkeypatch.setattr(
        generate_report, "get_client_for_org", lambda org, permissions=None: client
    )
    return client


def test_main_uses_client_for_configured_org():
    # Exercises the real `get_client_for_org` (unlike `mock_org_client`), to
    # check it routes to the "opensafely-core" org's installation and requests
    # the module's permissions.
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
        "workspace.utils.github_rest_api.create_github_client_for_org",
        return_value=fake_client,
    ) as mock_github_client_for_org:
        generate_report.main(13, ["Backlog"])
    mock_github_client_for_org.assert_called_once_with(
        123,
        {"organization_projects": "read", "issues": "read", "pull_requests": "read"},
    )


def test_generate_report(mock_org_client):
    mock_org_client.post_graphql.return_value = {
        "data": {
            "organization": {"projectV2": {"id": 1}},
            "node": {
                "items": {
                    "nodes": [
                        {
                            "id": "item1",
                            "type": "ISSUE",
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
                            "id": "item2",
                            "type": "ISSUE",
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
                            "id": "item3",
                            "type": "PULL_REQUEST",
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
            "text": {"type": "mrkdwn", "text": "• <http://card1|Card 1>\n"},
        },
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Blocked*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "• Card 3\n"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*In Progress*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "• Card 2\n"}},
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


# Same-org items missing repo permissions.
#
# The token used to fetch the project can see an item exists (it's in the
# project's own `items` connection) but can't read its content, because that
# repo's org hasn't granted the Issues/Pull requests permissions this needs.
# GitHub reports this as `type: REDACTED` with `content: None`.


def test_get_project_cards_omits_same_org_redacted_items(mock_org_client):
    mock_org_client.post_graphql.return_value = {
        "data": {
            "node": {
                "items": {
                    "nodes": [
                        {
                            "id": "item1",
                            "type": "REDACTED",
                            "content": None,
                            "fieldValues": {"nodes": []},
                        },
                        {
                            "id": "item2",
                            "type": "ISSUE",
                            "content": {
                                "title": "Same-org card",
                                "assignees": {"nodes": []},
                            },
                            "fieldValues": {"nodes": []},
                        },
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
    }

    cards, omitted_count = generate_report.get_project_cards(
        mock_org_client, project_id="proj1", org="opensafely-core"
    )
    assert omitted_count == 1
    assert [card["content"]["title"] for card in cards] == ["Same-org card"]


def test_main_appends_omitted_note_for_same_org_permission_gap(mock_org_client):
    mock_org_client.post_graphql.side_effect = [
        # 1) get the project ID
        {"data": {"organization": {"projectV2": {"id": 1}}}},
        # 2) get the project cards - one redacted item
        {
            "data": {
                "node": {
                    "items": {
                        "nodes": [
                            {
                                "id": "item1",
                                "type": "REDACTED",
                                "content": None,
                                "fieldValues": {"nodes": []},
                            },
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        },
    ]

    blocks = json.loads(generate_report.main(13, ["Blocked"]))
    assert blocks[-1] == {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "_1 item(s) omitted: the GitHub app doesn't have permission to "
                "read their content (ask an admin to grant the Issues/Pull "
                "requests permissions)._"
            ),
        },
    }
