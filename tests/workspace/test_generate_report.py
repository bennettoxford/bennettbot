import json

from workspace.report import generate_report


def test_generate_report():
    def mock_post_request(payload):
        return {
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

    generate_report.post_request = mock_post_request
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


def test_generate_report_with_custom_org():
    def mock_post_request(payload):
        # Verify the org parameter is passed to the query
        assert payload["variables"]["org_name"] == "custom-org"
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

    generate_report.post_request = mock_post_request

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


def test_generate_report_no_issues():
    def mock_post_request(payload):
        return {
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

    generate_report.post_request = mock_post_request

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
