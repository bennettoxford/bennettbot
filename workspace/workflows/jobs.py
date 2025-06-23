import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests

from bennettbot import settings
from workspace.utils import shorthands
from workspace.utils.argparse import SplitString
from workspace.utils.blocks import (
    get_basic_header_and_text_blocks,
    get_header_block,
    get_text_block,
)
from workspace.workflows import config


CACHE_PATH = settings.WRITEABLE_DIR / "workflows_cache.json"
TOKEN = os.environ["DATA_TEAM_GITHUB_API_TOKEN"]  # requires "read:project" and "repo"
EMOJI = {
    "success": ":large_green_circle:",
    "running": ":large_yellow_circle:",
    "failure": ":red_circle:",
    "skipped": ":white_circle:",
    "cancelled": ":heavy_multiplication_x:",
    "missing": ":ghost:",
    "other": ":grey_question:",
}


def get_emoji(conclusion) -> str:
    return EMOJI.get(conclusion, EMOJI["other"])


def get_locations_for_team(team: str) -> list[str]:
    return [
        f"{v['org']}/{repo}" for repo, v in config.REPOS.items() if v["team"] == team
    ]


def get_locations_for_org(org: str) -> list[str]:
    return [f"{org}/{repo}" for repo, v in config.REPOS.items() if v["org"] == org]


def report_invalid_target(target) -> str:
    blocks = get_basic_header_and_text_blocks(
        header_text=f"{target} was not recognised",
        texts=f"Run `@{settings.SLACK_APP_USERNAME} workflows usage` to see the valid values for `target`.",
    )
    return json.dumps(blocks)


def report_invalid_list_of_targets() -> str:
    blocks = get_basic_header_and_text_blocks(
        header_text="Invalid list of targets",
        texts=[
            "List items must all be orgs or all be repos.",
        ],
    )
    return json.dumps(blocks)


def get_api_result_as_json(url: str, params: dict | None = None) -> dict:
    params = params or {}
    params["format"] = "json"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text())


def get_github_actions_link(location):
    return f"https://github.com/{location}/actions?query=branch%3Amain"


class RepoWorkflowReporter:
    def __init__(self, location):
        """
        Retrieves and reports on the status of workflow runs on the main branch in a specified repo.
        Workflows that are not on the main branch are skipped.

        Creating an instance of this class will automatically call the GitHub API to get a list of workflow IDs and their names.
        Subsequently calling get_latest_conclusions() will call a different endpoint of the API to get the status and conclusion for the most recent run of each workflow.
        workflows_cache.json is updated with the conclusions and the timestamp of the retrieval, and API calls are only made for new runs since the last retrieval.

        report() will return a full JSON message with blocks for each workflow where the statuses of workflows are represented by emojis, as defined in the EMOJI dictionary.

        Functions outside of this class are used to generate summary reports from the conclusions returned from get_latest_conclusions() or loaded from the cache file.

        Parameters:
            location: str
                The location of the repo in the format "org/repo" (e.g. "opensafely/documentation")
        """
        self.location = location
        self.base_api_url = f"https://api.github.com/repos/{self.location}/"
        self.github_actions_link = get_github_actions_link(self.location)

        self.workflows = self.get_workflows()  # Dict of workflow_id: workflow_name
        self.workflow_ids = set(self.workflows.keys())

        self.cache = self._load_cache_for_repo()

    def _load_cache_for_repo(self) -> dict:
        return load_cache().get(self.location, {})

    @property
    def last_retrieval_timestamp(self):
        # Do not declare in __init__ to update this when self.cache is updated
        return self.cache.get("timestamp", None)

    def _get_json_response(self, path, params=None):
        url = urljoin(self.base_api_url, path)
        return get_api_result_as_json(url, params)

    def get_workflows(self) -> dict:
        results = self._get_json_response("actions/workflows")["workflows"]
        workflows = {wf["id"]: wf["name"] for wf in results}
        self.remove_ignored_workflows(workflows)
        return workflows

    def remove_ignored_workflows(self, workflows):
        skipped = config.IGNORED_WORKFLOWS.get(self.location, [])
        for workflow_id in skipped:
            workflows.pop(workflow_id, None)

    def get_runs(self, since_last_retrieval) -> list:
        params = {"branch": "main", "per_page": 100}
        if since_last_retrieval and self.last_retrieval_timestamp is not None:
            params["created"] = ">=" + self.last_retrieval_timestamp
        return self._get_json_response("actions/runs", params=params)["workflow_runs"]

    def get_latest_conclusions(self) -> dict:
        """
        Use the GitHub API to get the conclusion of the most recent run for each workflow.
        Update the cache file with the conclusions and the timestamp of the retrieval.
        """
        # Detect new runs and status updates for existing non-successful runs
        since_last_retrieval = (
            self.cache != {}
            and get_success_rate(list(self.cache["conclusions"].values())) == 1
        )

        # Use the moment just before calling the GitHub API as the timestamp
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        new_runs = self.get_runs(since_last_retrieval)
        latest_runs, missing_ids = self.find_latest_for_each_workflow(new_runs)
        conclusions = {
            run["workflow_id"]: self.get_conclusion_for_run(run) for run in latest_runs
        }
        self.fill_in_conclusions_for_missing_ids(conclusions, missing_ids)

        self.cache = {
            "timestamp": timestamp,
            # To be consistent with the JSON file which has the IDs as strings
            "conclusions": {str(k): v for k, v in conclusions.items()},
        }

        self.write_cache_to_file()
        return conclusions

    @staticmethod
    def get_conclusion_for_run(run) -> str:
        aliases = {"in_progress": "running"}
        if run["conclusion"] is None:
            status = str(run["status"])
            return aliases.get(status, status)
        return run["conclusion"]

    def fill_in_conclusions_for_missing_ids(self, conclusions, missing_ids):
        """
        For workflows that have not run since the last retrieval, use the conclusion from the cache.
        If no conclusion is found in the cache, mark the workflow as missing.
        """
        previous_conclusions = self.cache.get("conclusions", {})
        for workflow_id in missing_ids:
            id_str = str(workflow_id)  # In the cache JSON, IDs are stored as strings
            conclusions[workflow_id] = previous_conclusions.get(id_str, "missing")
        return

    def write_cache_to_file(self):
        cache_file_contents = load_cache()
        cache_file_contents[self.location] = self.cache
        with open(CACHE_PATH, "w") as f:
            f.write(json.dumps(cache_file_contents))

    def report(self) -> str:
        # This needs to be a class method as it uses self.workflows for names
        def format_text(workflow_id, conclusion) -> str:
            name = self.workflows[workflow_id]
            emoji = get_emoji(conclusion)
            return f"{name}: {emoji} {conclusion.title().replace('_', ' ')}"

        conclusions = self.get_latest_conclusions()
        lines = [format_text(wf, conclusion) for wf, conclusion in conclusions.items()]
        blocks = [
            get_header_block(f"Workflows for {self.location}"),
            get_text_block("\n".join(lines)),  # Show in one block for compactness
            get_text_block(f"<{self.github_actions_link}|View Github Actions>"),
        ]
        return json.dumps(blocks)

    def find_latest_for_each_workflow(self, all_runs) -> list:
        latest_runs = []
        found_ids = set()
        for run in all_runs:
            if run["workflow_id"] in found_ids:
                continue
            if run["workflow_id"] in self.workflow_ids:
                latest_runs.append(run)
                found_ids.add(run["workflow_id"])
            if found_ids == self.workflow_ids:
                return latest_runs, set()
        missing_ids = self.workflow_ids - found_ids
        return latest_runs, missing_ids


def get_summary_block(location: str, conclusions: list) -> str:
    link = get_github_actions_link(location)
    emojis = "".join([get_emoji(c) for c in conclusions])
    return get_text_block(f"<{link}|{location}>: {emojis}")


def get_success_rate(conclusions) -> float:
    return conclusions.count("success") / len(conclusions)


def _summarise(header_text: str, locations: list[str], skip_successful: bool) -> list:
    unsorted = {}
    for location in locations:
        wf_conclusions = RepoWorkflowReporter(location).get_latest_conclusions()

        # Skip reporting missing workflows and failures that are already known
        known_failure_ids = config.WORKFLOWS_KNOWN_TO_FAIL.get(location, [])
        wf_conclusions = {
            k: v
            for k, v in wf_conclusions.items()
            if v == "success" or (k not in known_failure_ids and v != "missing")
        }

        if len(wf_conclusions) == 0:
            continue

        if skip_successful and get_success_rate(list(wf_conclusions.values())) == 1:
            continue
        unsorted[location] = list(wf_conclusions.values())

    key = lambda item: get_success_rate(item[1])
    conclusions = sorted(unsorted.items(), key=key)

    blocks = [
        get_header_block(header_text),
        *[get_summary_block(loc, conc) for loc, conc in conclusions],
    ]
    return blocks


def summarise_team(team: str, skip_successful: bool) -> list:
    header = f"Workflows for {team}"
    locations = get_locations_for_team(team)
    return _summarise(header, locations, skip_successful)


def summarise_all(skip_successful) -> list:
    # Show in sections by team
    blocks = []
    for team in config.TEAMS:
        team_blocks = summarise_team(team, skip_successful)
        if len(team_blocks) > 1:
            blocks.extend(team_blocks)
    if len(blocks) == 0:
        blocks = [get_header_block("No workflow failures to report!")]
    return blocks


def summarise_org(org, skip_successful) -> list:
    header_text = f"Workflows for {org} repos"
    locations = get_locations_for_org(org)
    blocks = _summarise(header_text, locations, skip_successful)
    return blocks


def summarise_workflows_group(group: str, skip_successful: bool) -> list:
    """
    Summarise the status of a group of workflows with specified IDs.
    """
    try:
        group_config = config.CUSTOM_WORKFLOWS_GROUPS[group]
    except KeyError:
        return get_basic_header_and_text_blocks(
            header_text=f"Group {group} was not defined",
            texts=f"Available custom workflow groups are: {', '.join(config.CUSTOM_WORKFLOWS_GROUPS.keys())}",
        )

    conclusions = {}
    for location, workflow_ids in group_config["workflows"].items():
        wf_conclusions = RepoWorkflowReporter(location).get_latest_conclusions()
        conclusions[location] = [
            wf_conclusions.get(wf_id, "missing") for wf_id in workflow_ids
        ]
    blocks = [
        get_header_block(group_config["header_text"]),
        *[
            get_summary_block(loc, conc)
            for loc, conc in conclusions.items()
            if not (skip_successful and get_success_rate(conc) == 1)
        ],
    ]
    return blocks


def main(args) -> str:
    try:
        if args.group:
            # If a custom workflows group is passed, ignore target and summarise group
            return json.dumps(
                summarise_workflows_group(args.group, args.skip_successful)
            )
        return _main(args.target, args.skip_successful)
    except Exception as e:
        blocks = get_basic_header_and_text_blocks(
            header_text=f"An error occurred reporting workflows for {args.group or ' '.join(args.target)}",
            texts=str(e),
        )
        return json.dumps(blocks)


def _main(targets: list[str], skip_successful: bool) -> str:
    """
    Main function to report on the status of workflows in one or more specified targets.
    args:
        targets: list[str]
            List elements may be one of the following:
            - "all": Summarise all repos, sectioned by team
            - A known organisation to summarise
            - A known repo (the org/ prefix is optional)
            - A repo in the format org/repo (Note that the repo must still belong to a known org)
        skip_successful: bool
            If True, repos with all successful (i.e. all green) workflows will be skipped. Only used for summary functions.
    """

    if "all" in targets:
        return json.dumps(summarise_all(skip_successful))

    # Validation
    orgs = []
    locations = []
    for target in targets:
        # Some repos are names of websites and slack prepends http:// to them
        target = target.replace("http://", "")
        if target.count("/") > 1:
            return report_invalid_target(target)

        if "/" in target:  # Single repo in org/repo format
            org, repo = target.split("/")
        elif target in config.REPOS:  # Known repo
            org, repo = config.REPOS[target]["org"], target
        else:  # Assume target is an org
            org, repo = target, None

        org = shorthands.ORGS.get(org, org)
        if org not in shorthands.ORGS.values():
            return report_invalid_target(target)
        if repo:
            locations.append(f"{org}/{repo}")
        else:
            orgs.append(org)

    if orgs and not locations:  # Summarise the org(s)
        blocks = []
        for org in orgs:
            blocks.extend(summarise_org(org, skip_successful))
        return json.dumps(blocks)

    elif len(locations) != len(targets):
        return report_invalid_list_of_targets()

    elif len(locations) == 1:
        # Single repo usage: Report status for all workflows in a specified repo
        return RepoWorkflowReporter(locations[0]).report()

    else:  # Summarise the list of repos requested
        return json.dumps(_summarise("Workflows summary", locations, skip_successful))


def get_text_blocks_for_key(args) -> str:
    blocks = get_basic_header_and_text_blocks(
        header_text="Workflow status emoji key",
        texts=[f"{v}={k.title()}" for k, v in EMOJI.items()],
    )
    return json.dumps(blocks)


def get_workflow_runs_history(org, repo, days=90):
    runs = []
    url = f"https://api.github.com/repos/{org}/{repo}/actions/runs"
    params = {"branch": "main", "per_page": 100}
    headers = {"Authorization": f"Bearer {TOKEN}"}

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    while url:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        page_runs = data["workflow_runs"]

        # Filter runs by date and add to results
        for run in page_runs:
            run_date = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            if run_date >= cutoff_date:
                runs.append(run)
            else:
                # Runs are ordered by date, so we can stop here
                return runs

        # Parse Link header for next page URL
        links = requests.utils.parse_header_links(response.headers.get("Link", ""))
        next_url = None
        for link in links:
            if link.get("rel") == "next":
                next_url = link["url"]
                break
        url = next_url

    return runs


def get_workflow_history(args) -> str:
    # Get the first repo from the config
    repo_name, repo = next(iter(config.REPOS.items()))
    org = repo["org"]

    runs = get_workflow_runs_history(org, repo_name, days=90)

    blocks = get_basic_header_and_text_blocks(
        header_text="Workflow History",
        texts=f"First repo: {org}/{repo_name}\nNumber of workflow runs: {len(runs)}",
    )
    return json.dumps(blocks)


def get_usage_text(args) -> str:
    orgs = ", ".join([f"`{k} ({v})`" for k, v in shorthands.ORGS.items()])
    return "\n".join(
        [
            "Usage for `show [target]` (The behaviour for `show-failed [target]` is the same, but skips repos whose workflows are all successful):",
            "`show [all]`: Summarise all repos, sectioned by team.",
            f"`show [org]`: Summarise all repos for a known organisation, which is limited to the following shorthands and their full names: {orgs}.",
            "`show [repo]`: Report status for all workflows in a known repo (e.g. `show airlock`) or a repo in a known org (e.g. `show os/some-study-repo`).",
            "To pass multiple targets, separate them by spaces (e.g. `show os osc` or `show airlock ehrql`).",
            "When passing multiple targets, the targets should be of the same type (multiple orgs or multiple repos, but not a combination of both).",
            "",
            "List of known repos:",
            ", ".join(config.REPOS.keys()),
            "",
            "Usage for `show-group`:",
            f"`show-group [group]`: Summarise a custom group of workflows. Available groups are: {', '.join(config.CUSTOM_WORKFLOWS_GROUPS.keys())}.",
        ]
    )


def get_command_line_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True)

    # Main task: show workflows
    show_parser = subparsers.add_parser("show")
    show_parser.add_argument(
        "--target",
        default="all",
        action=SplitString,
        help="Provide multiple targets as a space-separated quoted string, e.g. 'os osc'.",
    )
    show_parser.add_argument("--group", required=False)
    show_parser.add_argument("--skip-successful", action="store_true", default=False)
    show_parser.set_defaults(func=main)

    # History task: show workflow history
    history_parser = subparsers.add_parser("history")
    history_parser.set_defaults(func=get_workflow_history)

    # Display key
    key_parser = subparsers.add_parser("key")
    key_parser.set_defaults(func=get_text_blocks_for_key)

    # Display usage
    usage_text_parser = subparsers.add_parser("usage")
    usage_text_parser.set_defaults(func=get_usage_text)
    return parser


if __name__ == "__main__":
    try:
        args = get_command_line_parser().parse_args()
        print(args.func(args))
    except Exception as e:
        print(
            json.dumps(
                get_basic_header_and_text_blocks(
                    header_text="An error occurred", texts=str(e)
                )
            )
        )
