import argparse
import json

from workspace.utils import repos_config
from workspace.utils.argparse import SplitCommaSeparatedString
from workspace.utils.blocks import get_basic_header_and_text_blocks
from workspace.utils.github_rest_api import get_client_for_org
from workspace.utils.people import People


ORG_NAME = "opensafely-core"
# Requires the Organization "Organization projects" app permission (read)
# and Repo Issues and Pull Requests permissions (for reading the content
# of project board items from private repos).
GITHUB_PERMISSIONS = {
    "organization_projects": "read",
    "issues": "read",
    "pull_requests": "read",
}


def main(project_num, statuses, org=ORG_NAME):
    org = repos_config.org_shorthands().get(org, org)
    client = get_client_for_org(org, permissions=GITHUB_PERMISSIONS)
    project_id = get_project_id(client, int(project_num), org)
    cards, omitted_count = get_project_cards(client, project_id, org)
    tickets_by_status = {status: [] for status in statuses}

    for card in cards:  # pragma: no cover
        status, summary = get_status_and_summary(card)
        if status and status in statuses:
            tickets_by_status[status].append(summary)

    report_output = get_basic_header_and_text_blocks(
        header_text=":newspaper: Project Board Summary :newspaper:",
        texts=f"<https://github.com/orgs/{org}/projects/{project_num}/views/1|View board>",
    )

    for status, tickets in tickets_by_status.items():
        if tickets:
            ticket_list = "".join(f"• {ticket}\n" for ticket in tickets)
            report_output.extend(
                [
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*{status}*"},
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": ticket_list},
                    },
                ]
            )

    if omitted_count:
        report_output.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"_{omitted_count} item(s) omitted: the GitHub token doesn't have "
                        "permission to read their content._"
                    ),
                },
            }
        )

    report_output.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"_Note: items on private repos that are not in {org} are not "
                    "displayed in this report._"
                ),
            },
        }
    )

    return json.dumps(report_output)


def get_project_id(client, project_num, org):
    query = """
    query projectId($org_name: String!, $project_num: Int!) {
      organization(login: $org_name) {
        projectV2(number: $project_num) {
          id
          title
        }
      }
    }
    """
    variables = {
        "org_name": org,
        "project_num": project_num,
    }

    rsp = client.post_graphql(query, variables)
    return rsp["data"]["organization"]["projectV2"]["id"]


def get_project_cards(client, project_id, org):
    query = """
    query projectCards($project_id: ID!, $cursor: String) {
      node(id: $project_id) {
        ... on ProjectV2 {
          items(first: 100, after: $cursor) {
            nodes {
              id
              type
              fieldValues(last: 100) {
                nodes {
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    name
                    field {
                      ... on ProjectV2FieldCommon {
                        name
                      }
                    }
                  }
                }
              }
              content {
                ... on DraftIssue {
                  title
                  assignees(first: 10) {
                    nodes {
                      login
                    }
                  }
                }
                ... on Issue {
                  title
                  bodyUrl
                  assignees(first: 10) {
                    nodes {
                      login
                    }
                  }
                }
                ... on PullRequest {
                  title
                  assignees(first: 10) {
                    nodes {
                      login
                    }
                  }
                }
              }
            }
            pageInfo {
              endCursor
              hasNextPage
            }
          }
        }
      }
    }
    """

    cursor = None
    project_data = []
    while True:
        variables = {"project_id": project_id, "cursor": cursor, "org_name": org}
        data = client.post_graphql(query, variables)
        node_data = data["data"]["node"]["items"]
        project_data.extend(node_data["nodes"])
        if not node_data["pageInfo"]["hasNextPage"]:
            break
        # update the cursor we pass into the GraphQL query
        cursor = node_data["pageInfo"]["endCursor"]  # pragma: no cover
    # If the token can't read the content of an item, it's in the project's
    # org but the app/user hasn't been given the right permissions on the repo.
    # Note (rebkwok 2026-09-28): according to the API docs, GitHub reports this
    # as `type: REDACTED` with null `content`; I haven't seen `type: REDACTED`
    # actually happen in the wild, and the behaviour appears for non-permitted
    # items is different with app installation tokens and finegrained PATs.
    # With an app installation token (i.e. in prod), items without permission are
    # omitted entirely.
    # With a finegrained user PAT without permission, they are returned with issue
    # type ISSUE and null content (assuming the user who owns the token has permission
    # to see the items, the org-scoped token is allowed to know that the item exists,
    # but not to view its content.)
    cards = [card for card in project_data if card["content"] is not None]
    omitted_count = len(project_data) - len(cards)

    return (
        sorted(cards, key=lambda card: card["content"]["title"]),
        omitted_count,
    )


def get_status_and_summary(card):  # pragma: no cover
    for node in card["fieldValues"]["nodes"]:
        if "field" not in node:
            continue
        if node["field"]["name"] != "Status":
            continue
        status = node["name"]
        break
    else:
        # This card has no status
        return (None, None)
    title = card["content"]["title"]
    url = card["content"].get("bodyUrl")
    assignees = " / ".join(
        People.by_github_username(node["login"]).formatted_slack_username
        for node in card["content"]["assignees"]["nodes"]
    )

    if url:
        summary = f"<{url}|{title}>"
    else:
        summary = title

    if assignees:
        summary = f"{summary} ({assignees})"

    return status, summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-num", type=int, help="The GitHub Project number")
    parser.add_argument(
        "--statuses",
        type=str,
        action=SplitCommaSeparatedString,
        help="List of GitHub Project statuses",
    )
    parser.add_argument("--org", default=ORG_NAME, help="GitHub organization name")
    args = parser.parse_args()
    print(main(args.project_num, args.statuses, args.org))
