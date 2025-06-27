import argparse
import json
import os
import warnings
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import pandas as pd
import plotly.graph_objects as go
import requests
from plotly.subplots import make_subplots

from bennettbot import settings
from workspace.utils import shorthands
from workspace.utils.argparse import SplitString
from workspace.utils.blocks import (
    get_basic_header_and_text_blocks,
    get_header_block,
    get_text_block,
)
from workspace.workflows import config


# Suppress pandas deprecation warning for .dt.to_pydatetime()
warnings.filterwarnings(
    "ignore",
    "The behavior of DatetimeProperties.to_pydatetime is deprecated",
    FutureWarning,
)

# Enable caching for local development
if os.environ.get("ENABLE_HTTP_CACHE"):
    import requests_cache

    requests_cache.install_cache(
        cache_name="github_api_cache",
        backend="sqlite",
        expire_after=60 * 60 * 24,  # 1 day
    )


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


def get_workflow_runs(start_time):
    runs = []

    for repo_name, repo in config.REPOS.items():
        org = repo["org"]

        url = f"https://api.github.com/repos/{org}/{repo_name}/actions/runs"
        params = {"branch": "main", "per_page": 100}
        headers = {"Authorization": f"Bearer {TOKEN}"}

        while url:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            found_old_run = False

            for run in data["workflow_runs"]:
                run_date = datetime.fromisoformat(
                    run["created_at"].replace("Z", "+00:00")
                )
                if run_date < start_time:
                    # Runs are ordered by date, so we can stop here
                    found_old_run = True
                    break
                runs.append(
                    (
                        org,
                        repo_name,
                        run.get("workflow_id"),
                        run_date,
                        run.get("conclusion"),
                    )
                )

            if found_old_run:
                break

            links = requests.utils.parse_header_links(response.headers.get("Link", ""))
            url = next(
                (link["url"] for link in links if link.get("rel") == "next"), None
            )

    return runs


def remove_excluded_workflows(runs):
    exclusions = {}
    for repo_name, repo in config.REPOS.items():
        location = f"{repo['org']}/{repo_name}"
        ignored = config.IGNORED_WORKFLOWS.get(location, [])
        known_to_fail = config.WORKFLOWS_KNOWN_TO_FAIL.get(location, [])
        exclusions[(repo["org"], repo_name)] = set(ignored + known_to_fail)

    return [
        (org, repo, workflow, date, conclusion)
        for org, repo, workflow, date, conclusion in runs
        if workflow not in exclusions[(org, repo)]
    ]


def strip_repo(runs):
    return [
        (workflow, date, conclusion) for org, repo, workflow, date, conclusion in runs
    ]


def convert_states(runs):
    converted = []

    for workflow, date, conclusion in runs:
        # Skip runs that haven't finished
        if not conclusion:
            continue

        # Skip skipped and startup_failure runs - leave previous status undisturbed
        if conclusion in ["skipped", "startup_failure"]:
            continue

        assert conclusion in [
            "success",
            "failure",
            "cancelled",
            "timed_out",
        ], f"Unexpected conclusion: {conclusion}"

        converted.append((workflow, date, conclusion == "success"))

    return converted


def build_workflows(runs):
    workflows = defaultdict(list)

    for workflow, date, success in runs:
        workflows[workflow].append((date, success))

    for workflow in workflows:
        workflows[workflow] = sorted(workflows[workflow], key=lambda x: x[0])

    return workflows


def add_recoveries(workflows):
    with_recoveries = defaultdict(list)
    for workflow, state_changes in workflows.items():
        for i, (date, success) in enumerate(state_changes):
            recovery = None
            if not success:
                for j in range(i + 1, len(state_changes)):
                    next_date, next_success = state_changes[j]
                    if next_success:
                        recovery = (next_date - date).total_seconds() / 3600
                        break
            with_recoveries[workflow].append((date, success, recovery))
    return with_recoveries


def build_spans(workflows):
    spans = defaultdict(list)
    for workflow, runs in workflows.items():
        last_success = None
        for date, success, _ in runs:
            if success == last_success:
                continue
            spans[workflow].append((date, success))
            last_success = success
    return spans


def get_yesterday_end():
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    return datetime.combine(yesterday, datetime.max.time()).replace(tzinfo=None)


def get_week_frequency():
    today = datetime.now().date()
    yesterday_weekday = (today.weekday() - 1) % 7
    weekday_to_freq = {
        0: "W-MON",  # yesterday was Monday
        1: "W-TUE",  # yesterday was Tuesday
        2: "W-WED",  # yesterday was Wednesday
        3: "W-THU",  # yesterday was Thursday
        4: "W-FRI",  # yesterday was Friday
        5: "W-SAT",  # yesterday was Saturday
        6: "W-SUN",  # yesterday was Sunday
    }
    return weekday_to_freq[yesterday_weekday]


def calculate_stats(workflows):
    df = pd.DataFrame(
        (
            (workflow, date, success, recovery)
            for workflow, runs in workflows.items()
            for date, success, recovery in runs
        ),
        columns=["workflow", "date", "success", "recovery"],
    )

    # Filter out today's data, which is part of an incomplete week
    yesterday_end = get_yesterday_end()
    df["date"] = df["date"].dt.tz_localize(None)  # avoids period conversion warning
    df = df[df["date"] <= yesterday_end]

    # Use dynamic week frequency that ends yesterday
    df["week"] = df["date"].dt.to_period(get_week_frequency())

    stats = (
        df.groupby("week")
        .agg(
            {
                "success": [
                    "count",
                    lambda x: (~x).sum(),
                ],  # sum give number of failures
                "recovery": ["mean", "sum"],
                "workflow": "nunique",
            }
        )
        .round(3)
    )
    stats.columns = [
        "total_runs",
        "failed_runs",
        "recovery_time",
        "downtime_duration",
        "active_workflows",
    ]
    stats["week_start"] = stats.index.to_timestamp()

    stats["failure_rate"] = stats["failed_runs"] / stats["total_runs"] * 100
    stats["downtime_per_workflow"] = (
        stats["downtime_duration"] / stats["active_workflows"]
    )

    return stats


def add_metric_chart(fig, stats, row, x_range, y_column, color, y_title):
    fig.add_trace(
        go.Scatter(
            x=stats["week_start"].dt.to_pydatetime(),
            y=stats[y_column].values,
            mode="lines+markers",
            line=dict(color=color, width=3),
            marker=dict(size=6, color=color),
            showlegend=False,
        ),
        row=row,
        col=1,
    )

    fig.update_xaxes(
        type="date",
        range=x_range,
        showgrid=True,
        gridcolor="lightgray",
        showticklabels=False,
        row=row,
        col=1,
    )

    y_max = stats[y_column].max()
    fig.update_yaxes(
        range=[0, y_max * 1.1],
        showgrid=True,
        gridcolor="lightgray",
        title_text=y_title,
        row=row,
        col=1,
    )


def add_failure_rates(fig, stats, x_range, row):
    add_metric_chart(
        fig, stats, row, x_range, "failure_rate", "#E74C3C", "Failure rate (%)"
    )


def add_mttr(fig, stats, x_range, row):
    add_metric_chart(fig, stats, row, x_range, "recovery_time", "#3498DB", "MTTR (hrs)")


def add_downtime(fig, stats, x_range, row):
    add_metric_chart(
        fig,
        stats,
        row,
        x_range,
        "downtime_per_workflow",
        "#8E44AD",
        "Downtime per<br>workflow (hrs)",
    )


def add_statuses(fig, spans, x_range, row=4):
    def mk_shape(start, end, y, colour):
        # Create exact pixel boundaries: 7px stripe + 1px gap
        # y is workflow index, so stripe goes from y*8 to y*8+7 (7px high)
        # leaving 1px gap before next stripe at (y+1)*8
        return {
            "type": "rect",
            "x0": start,
            "x1": end,
            "y0": y * 8,
            "y1": y * 8 + 7,
            "fillcolor": colour,
            "line": dict(width=0),
            "layer": "below",
            "xref": f"x{row}",
            "yref": f"y{row}",
        }

    # Add empty trace to establish axes
    # Use pixel coordinates: workflows range from 0 to (len(spans)-1)*8+7
    max_y = (len(spans) - 1) * 8 + 7
    fig.add_trace(
        go.Scatter(
            x=x_range,
            y=[0, max_y],
            mode="markers",
            marker=dict(size=0.1, color="rgba(0,0,0,0)"),
            showlegend=False,
            hoverinfo="skip",
        ),
        row=row,
        col=1,
    )

    start_time, end_time = x_range
    shapes = []
    for i, runs in enumerate(spans.values()):
        last_start, colour = start_time, "gray"

        for timestamp, success in runs:
            shapes.append(mk_shape(last_start, timestamp, i, colour))
            last_start = timestamp
            colour = "green" if success else "red"

        shapes.append(mk_shape(last_start, end_time, i, colour))

    fig.update_layout(shapes=shapes)

    fig.update_xaxes(
        type="date",
        range=x_range,
        showgrid=True,
        gridcolor="lightgray",
        showticklabels=True,
        ticklabelstandoff=20,
        row=row,
        col=1,
    )

    fig.update_yaxes(
        showticklabels=False,
        range=[-1, max_y + 1],
        showgrid=False,
        zeroline=False,
        row=row,
        col=1,
    )


def calculate_chart_dimensions(num_workflows, chart_width=800):
    """Calculate chart dimensions to ensure whole pixel heights for workflow stripes."""
    # Back to 8-pixel stripe height that worked (7px stripe + 1px gap)
    stripe_height = 8  # 7px stripe + 1px gap

    # Calculate status chart height needed for integer pixel stripes
    status_chart_height = num_workflows * stripe_height

    # Back to original working heights
    stats_chart_height = 120  # Height for each of the 3 stats charts
    total_stats_height = 3 * stats_chart_height

    # Back to original margins
    top_margin = 80
    bottom_margin = 80
    title_space = 40

    # Calculate total height
    total_height = (
        top_margin
        + title_space
        + total_stats_height
        + status_chart_height
        + bottom_margin
    )

    # Calculate row height fractions
    total_chart_area = total_stats_height + status_chart_height
    stats_fraction = stats_chart_height / total_chart_area
    status_fraction = status_chart_height / total_chart_area

    return {
        "total_height": total_height,
        "chart_width": chart_width,
        "row_heights": [
            stats_fraction,
            stats_fraction,
            stats_fraction,
            status_fraction,
        ],
        "stripe_height": stripe_height,
    }


def create_chart(dimensions):
    """Create chart with calculated dimensions for pixel-perfect rendering."""
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=dimensions["row_heights"],
    )
    fig.update_layout(
        title="Workflow statistics (by week)",
        height=dimensions["total_height"],
        width=dimensions["chart_width"],
        showlegend=False,
        plot_bgcolor="white",
        margin=dict(l=60, r=20, t=80, b=80),
    )
    return fig


def get_workflow_history(_) -> str:
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=365)

    runs = get_workflow_runs(start_time)
    runs = remove_excluded_workflows(runs)
    runs = strip_repo(runs)
    runs = convert_states(runs)
    workflows = build_workflows(runs)
    workflows = add_recoveries(workflows)
    spans = build_spans(workflows)
    stats = calculate_stats(workflows)

    # Calculate dimensions for pixel-perfect rendering
    num_workflows = len(spans)
    dimensions = calculate_chart_dimensions(num_workflows)

    x_range = [start_time, end_time]
    fig = create_chart(dimensions)
    add_failure_rates(fig, stats, x_range, row=1)
    add_mttr(fig, stats, x_range, row=2)
    add_downtime(fig, stats, x_range, row=3)
    add_statuses(fig, spans, x_range, row=4)

    chart_path = "workflow-history.png"
    fig.write_image(
        chart_path, width=dimensions["chart_width"], height=dimensions["total_height"]
    )

    return json.dumps(
        get_basic_header_and_text_blocks(
            header_text="Workflow History",
            texts=[f"Workflow history saved to: {chart_path}"],
        )
    )


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
        raise e
        print(
            json.dumps(
                get_basic_header_and_text_blocks(
                    header_text="An error occurred", texts=str(e)
                )
            )
        )
