import argparse
import json
import os
from datetime import datetime
from urllib.parse import urljoin

import requests

from bennettbot import settings
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
        texts=[
            "Argument must be a known organisation or repo, or a repo given as [org/repo].",
            f"Run `@{settings.SLACK_APP_USERNAME} workflows help` to see the available organisations.",
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
        self.remove_workflows_skipped_on_main(workflows)
        return workflows

    def remove_workflows_skipped_on_main(self, workflows):
        skipped = config.SKIPPED_WORKFLOWS_ON_MAIN.get(self.location, [])
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


def main(args) -> str:
    try:
        # Some repos are names of websites and slack prepends http:// to them
        return _main(args.target.replace("http://", ""), args.skip_successful)
    except Exception as e:
        blocks = get_basic_header_and_text_blocks(
            header_text=f"An error occurred reporting workflows for {args.target}",
            texts=str(e),
        )
        return json.dumps(blocks)


def _main(target: str, skip_successful: bool) -> str:
    """
    Main function to report on the status of workflows in a specified target.
    args:
        target:
            May be one of the following:
            - "all": Summarise all repos, sectioned by team
            - A known organisation to summarise
            - A known repo (the org/ prefix is optional)
            - A repo in the format org/repo (Note that the repo must still belong to a known org)
        skip_successful: bool
            If True, repos with all successful (i.e. all green) workflows will be skipped. Only used for summary functions.
    """
    if target == "all":
        return json.dumps(summarise_all(skip_successful))

    if target.count("/") > 1:
        return report_invalid_target(target)

    if "/" in target:  # Single repo in org/repo format
        org, repo = target.split("/")
    elif target in config.REPOS:  # Known repo
        org, repo = config.REPOS[target]["org"], target
    else:  # Assume target is an org
        org, repo = target, None

    org = config.SHORTHANDS.get(org, org)
    if org not in config.SHORTHANDS.values():
        return report_invalid_target(target)
    if repo:
        # Single repo usage: Report status for all workflows in a specified repo
        return RepoWorkflowReporter(f"{org}/{repo}").report()
    # Summarise status for multiple repos in an org
    return json.dumps(summarise_org(org, skip_successful))


def get_blocks_for_custom_workflow_list(args):
    job_config = config.CUSTOM_JOBS[args.job_name]
    header_text = job_config["header_text"]
    workflows = job_config["workflows"]
    conclusions = {}
    for location, workflow_ids in workflows.items():
        wf_conclusions = RepoWorkflowReporter(location).get_latest_conclusions()
        conclusions[location] = [
            wf_conclusions.get(wf_id, "missing") for wf_id in workflow_ids
        ]
    blocks = [
        get_header_block(header_text),
        *[get_summary_block(loc, conc) for loc, conc in conclusions.items()],
    ]
    return json.dumps(blocks)


def get_text_blocks_for_key(args) -> str:
    blocks = get_basic_header_and_text_blocks(
        header_text="Workflow status emoji key",
        texts=[f"{v}={k.title()}" for k, v in EMOJI.items()],
    )
    return json.dumps(blocks)


def get_command_line_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True)

    # Main task: show workflows
    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("--target", required=True)
    show_parser.add_argument("--skip-successful", action="store_true", default=False)
    show_parser.set_defaults(func=main)

    # Custom tasks
    custom_parser = subparsers.add_parser("custom")
    custom_parser.add_argument("--job-name", required=True)
    custom_parser.set_defaults(func=get_blocks_for_custom_workflow_list)

    # Display key
    key_parser = subparsers.add_parser("key")
    key_parser.set_defaults(func=get_text_blocks_for_key)
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
