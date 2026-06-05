"""
Queries the GitHub REST API "List Codespaces for the organization" endpoint
and shows the Codespaces that are "at risk" of being deleted, defined as having
uncommitted or unpushed changes and the retention period expiry being within
some threshold.

Refer to the codespaces playbook in the team manual for how this is used.
As of 2025-01, that's located at:
https://github.com/ebmdatalab/team-manual/blob/main/docs/tech-group/playbooks/codespaces.md
"""

import argparse
import collections
import datetime
import json
import os

from slack_sdk.models.blocks import (
    HeaderBlock,
    RichTextBlock,
    RichTextElementParts,
    RichTextListElement,
    RichTextSectionElement,
)

from workspace.utils.github_rest_api import GitHubAPIClient


CODE = RichTextElementParts.TextStyle(code=True)
BOLD = RichTextElementParts.TextStyle(bold=True)
Text = RichTextElementParts.Text
Link = RichTextElementParts.Link
Emoji = RichTextElementParts.Emoji


URL_PATTERN = "https://api.github.com/orgs/{org}/codespaces"
# The token can be a classic PAT with the admin:org scope or a fine-grained
# token with "Codespaces" repository permissions set to "read" and
# "Organization codespaces" organization permissions set to "read".
# https://docs.github.com/en/rest/codespaces/organizations?apiVersion=2022-11-28#list-codespaces-for-the-organization
# Someone with admin permissions on the organization needs to create it.
# For the opensafely org, created PATs should be stored in BitWarden.
github_client = GitHubAPIClient(
    os.environ["CODESPACES_GITHUB_API_TOKEN"], api_version="2022-11-28"
)


Codespace = collections.namedtuple(
    "Codespace",
    [
        "owner",
        "name",
        "repo",
        "retention_expires_at",
        "remaining_retention_period_days",
        "retention_period_days",
        "has_uncommitted",
        "has_unpushed",
    ],
)


def get_codespace(record):
    if record["retention_expires_at"]:
        retention_expires_at = datetime.datetime.fromisoformat(
            record["retention_expires_at"]
        )
        now = datetime.datetime.now(retention_expires_at.tzinfo)
        # This "rounds down", eg 10.7 days will be reported as 10 days as it
        # throws aways the parts smaller than one day. This seems fine.
        remaining_retention_period_days = (retention_expires_at - now).days
    else:
        # Codespaces may not have a retention period if the user has manually
        # chosen to keep the codespace indefinitely, which we allow. Also very
        # new codespaces may not have this set by GitHub yet. Don't report.
        retention_expires_at = None
        remaining_retention_period_days = None

    if record["retention_period_minutes"]:
        minutes_per_day = 60 * 24  # 60m per hour, 24 hours per day.
        # This could be rounded down to 0 if set to less than a day. Probably
        # nobody will do this, but if they do they're out of scope, as we have
        # little chance of warning them usefully.
        retention_period_days = record["retention_period_minutes"] // minutes_per_day
    else:
        # The user has manually chosen to keep the codespace indefinitely.
        retention_period_days = None

    return Codespace(
        owner=record["owner"]["login"],
        name=record["name"],
        repo=record["repository"]["name"],
        retention_expires_at=retention_expires_at,
        remaining_retention_period_days=remaining_retention_period_days,
        retention_period_days=retention_period_days,
        has_uncommitted=record["git_status"]["has_uncommitted_changes"],
        has_unpushed=record["git_status"]["has_unpushed_changes"],
    )


def is_at_risk(codespace, threshold_in_days):
    if codespace.remaining_retention_period_days is not None:
        close_to_expiry = codespace.remaining_retention_period_days <= threshold_in_days
        return close_to_expiry and (codespace.has_unpushed or codespace.has_uncommitted)
    else:
        # The user has manually chosen to keep the codespace indefinitely,
        # therefore there's no risk of them losing their work.
        return False


def main(threshold_in_days):
    # These could be parameters instead of hard-coded but no need for now.
    org = "opensafely"
    excluded_repos = [
        # Repos unlikely to contain valuable work product.
        # Template for tutorial.
        "ehrql-tutorial",
        # Tagged non-research.
        "research-template",
        "roadmap",
        "documentation",
    ]

    # Fetch info on org CodeSpaces at risk from GitHub API.
    records = github_client.get_paginated_json(
        URL_PATTERN.format(org=org), results_key="codespaces"
    )
    codespaces = (get_codespace(rec) for rec in records)
    at_risk_codespaces = sorted(
        (
            cs
            for cs in codespaces
            if is_at_risk(cs, threshold_in_days) and cs.repo not in excluded_repos
        ),
        key=lambda cs: cs.remaining_retention_period_days,
    )

    # Construct Slack rich text blocks for formatted output.
    # Blocks reference: https://api.slack.com/reference/block-kit/blocks
    # API reference: https://tools.slack.dev/python-slack-sdk/api-docs/slack_sdk/models/blocks/index.html
    if at_risk_codespaces:
        intro_block = RichTextSectionElement(
            elements=[
                Text(text=("For how to use this report, refer to ")),
                Link(
                    url="https://github.com/ebmdatalab/team-manual/blob/main/docs/tech-group/playbooks/codespaces.md",
                    text="the Codespaces playbook",
                ),
                Text(text=". "),
                Text(text=org, style=CODE),
                Text(
                    text=(
                        " Codespaces with unsaved work at risk (expiring within "
                        f"{threshold_in_days} days):"
                    )
                ),
            ]
        )

        list_items = [
            RichTextSectionElement(
                elements=[
                    Text(text="User", style=BOLD),
                    Text(text=": "),
                    Text(text=cs.owner, style=CODE),
                    Text(text=" Repo", style=BOLD),
                    Text(text=": "),
                    Text(text=cs.repo, style=CODE),
                    Text(text=" Deletion", style=BOLD),
                    Text(text=": "),
                    Text(
                        text=f"in {remaining_days_text} "
                        f"({cs.retention_expires_at:%A, %b %d at %H:%M}) "
                    ),
                    Text(text="ID", style=BOLD),
                    Text(text=": "),
                    Text(text=cs.name, style=CODE),
                    Text(text=" Retention", style=BOLD),
                    Text(text=f": {cs.retention_period_days} days "),
                    Text(text="Uncommitted", style=BOLD),
                    Text(text=f": {'Yes' if cs.has_uncommitted else 'No'} "),
                    Text(text="Unpushed", style=BOLD),
                    Text(text=f": {'Yes' if cs.has_unpushed else 'No'}"),
                ]
            )
            for cs in at_risk_codespaces
            if (
                remaining_days_text := (
                    "<1 day"
                    if not cs.remaining_retention_period_days
                    else str(cs.remaining_retention_period_days) + " days"
                )
            )
        ]
    else:
        intro_block = RichTextSectionElement(
            elements=[
                Text(text="No "),
                Text(text=org, style=CODE),
                Text(
                    text=(
                        " Codespaces with unsaved work at risk (expiring within "
                        f"{threshold_in_days} days) "
                    )
                ),
                Emoji(name="tada"),
            ]
        )
        list_items = []

    # JSON stringified representation of the desired output blocks.
    return json.dumps(
        [
            HeaderBlock(text="Codespaces at risk report").to_dict(),
            RichTextBlock(
                elements=[
                    intro_block,
                    RichTextListElement(elements=list_items, style="bullet"),
                ]
            ).to_dict(),
        ],
        indent=2,  # For human-readability. Logs are very small.
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Report Codespaces at risk of being deleted"
    )
    parser.add_argument(
        "threshold_in_days",
        type=int,
        help="Threshold in days for Codespaces to be considered 'at risk'",
    )
    args = parser.parse_args()

    print(main(args.threshold_in_days))
