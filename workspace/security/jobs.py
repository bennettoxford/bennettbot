import argparse
import json
import os

from bennettbot import settings
from workspace.utils import repos_config as config
from workspace.utils.argparse import SplitString
from workspace.utils.blocks import (
    get_basic_header_and_text_blocks,
    get_header_block,
    get_text_block,
)
from workspace.utils.github_rest_api import GitHubAPIClient


# Requires `repo` scope (only needs `security_events` for public repos, but full
# `repo` for private-repo access).
github_client = GitHubAPIClient(os.environ["DATA_TEAM_GITHUB_API_TOKEN"])

# Local cache of the most recent Dependabot response per (repo, severities),
# keyed by `"<repo>|<sev1>,<sev2>,…"`. Each entry stores the first-page ETag
# plus the full alerts list, so we can send `If-None-Match` on subsequent
# requests and skip re-downloading on 304 Not Modified.
CACHE_PATH = settings.WRITEABLE_DIR / "security_cache.json"


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text())


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache))


ALL_SEVERITIES = ["critical", "high", "medium", "low"]
DEFAULT_SEVERITIES = ["critical", "high"]
SEVERITY_EMOJI = {
    "critical": ":red_circle:",
    "high": ":large_orange_circle:",
    "medium": ":large_yellow_circle:",
    "low": ":large_blue_circle:",
}


def _top_header_text(severities: list[str]) -> str:
    if set(severities) == set(ALL_SEVERITIES):
        body = "Open Security Alerts"
    else:
        body = f"Open {'/'.join(s.title() for s in severities)} Security Alerts"
    return f":rotating_light: {body} :rotating_light:"


def _nothing_to_report_text(severities: list[str]) -> str:
    if set(severities) == set(ALL_SEVERITIES):
        body = "No open security alerts to report!"
    else:
        body = f"No open {' or '.join(severities)} severity alerts to report!"
    return f":white_check_mark: {body}"


def get_dependabot_alerts_link(repo_full_name: str) -> str:
    return f"https://github.com/{repo_full_name}/security/dependabot"


class RepoAlertsReporter:
    def __init__(self, repo_full_name: str, severities: list[str] | None = None):
        """
        Fetches and reports on open Dependabot security alerts for a single repo.

        Parameters:
            repo_full_name: "org/repo" string (e.g. "opensafely-core/airlock").
            severities: severities to fetch and report on. Defaults to critical/high.
        """
        self.repo_full_name = repo_full_name
        self.severities = severities or DEFAULT_SEVERITIES
        self.base_api_url = f"https://api.github.com/repos/{repo_full_name}/"
        self.dependabot_link = get_dependabot_alerts_link(repo_full_name)
        self.alerts = self.get_open_alerts()

    def _cache_key(self) -> str:
        # Severities are part of the key because the API filters server-side
        # by `severity=…`; an entry cached for critical/high would silently
        # return the wrong data for an all-severities request.
        return f"{self.repo_full_name}|{','.join(self.severities)}"

    def get_open_alerts(self) -> list:
        """Fetch alerts, sending the cached ETag if available. On 304 we reuse the
        cached alerts list; on 200 we replace the cache entry with the fresh response.
        """
        cache = load_cache()
        cached = cache.get(self._cache_key(), {})
        url = f"{self.base_api_url}dependabot/alerts"
        params = {
            "state": "open",
            "severity": ",".join(self.severities),
            "per_page": 100,
        }
        response = github_client.get_paginated_json(
            url, params=params, etag=cached.get("etag")
        )
        if response.not_modified:
            return cached["alerts"]
        alerts = list(response)
        cache[self._cache_key()] = {"etag": response.etag, "alerts": alerts}
        save_cache(cache)
        return alerts

    def get_counts(self) -> dict:
        counts = {sev: 0 for sev in self.severities}
        for alert in self.alerts:
            severity = alert.get("security_advisory", {}).get("severity")
            # We request the severities from the api endpoint, but just in case the
            # we get something unexpected in the response, make sure that each
            # severity is one we expect
            if severity in counts:
                counts[severity] += 1
        return counts

    def report_blocks(self) -> list:
        counts = self.get_counts()
        text = ", ".join(
            f"{SEVERITY_EMOJI[sev]} {counts[sev]} {sev}" for sev in self.severities
        )
        header = _top_header_text(self.severities) + f" for {self.repo_full_name}"
        return [
            get_header_block(header),
            get_text_block(text),
            get_text_block(f"<{self.dependabot_link}|View security alerts>"),
        ]


def get_summary_block(repo_full_name: str, counts: dict, severities: list[str]) -> dict:
    link = get_dependabot_alerts_link(repo_full_name)
    parts = [
        f"{SEVERITY_EMOJI[sev]} {counts[sev]} {sev}"
        for sev in severities
        if counts[sev] > 0
    ]
    return get_text_block(f"<{link}|{repo_full_name}>: {', '.join(parts)}")


def get_subheader_block(text: str) -> dict:
    return get_text_block(f"*{text}*")


def _repos_with_alerts(repo_full_names: list[str], severities: list[str]) -> list:
    items = []
    for repo_full_name in repo_full_names:
        counts = RepoAlertsReporter(repo_full_name, severities=severities).get_counts()
        if any(counts.values()):
            items.append((repo_full_name, counts))
    return items


def _section_blocks(
    subheader: str, repo_full_names: list[str], severities: list[str]
) -> list:
    """Subheader + repo summary lines for repos that have alerts. Empty if none."""
    items = _repos_with_alerts(repo_full_names, severities)
    if not items:
        return []
    return [
        get_subheader_block(subheader),
        *[
            get_summary_block(repo_full_name, counts, severities)
            for repo_full_name, counts in items
        ],
    ]


def _wrap_with_top_header(
    body: list, severities: list[str], quiet: bool = False
) -> list:
    if not body:
        # Nothing to report - either return [], as a valid blocks output,
        # which main() will turn into an empty string, or the nothing-to-report text
        if quiet:
            return []
        return [get_header_block(_nothing_to_report_text(severities))]
    return [get_header_block(_top_header_text(severities)), *body]


def get_excluded_repos() -> list[str]:
    return config.security_config().get("excluded_repos") or []


def summarise_team(team: str, severities: list[str]) -> list:
    return _section_blocks(
        team,
        config.get_repo_full_names_for_team(team, exclude=get_excluded_repos()),
        severities,
    )


def summarise_org(org: str, severities: list[str]) -> list:
    return _section_blocks(
        org,
        config.get_repo_full_names_for_org(org, exclude=get_excluded_repos()),
        severities,
    )


def summarise_all(severities: list[str], quiet: bool = False) -> list:
    body = []
    for team in config.teams():
        body.extend(summarise_team(team, severities))
    return _wrap_with_top_header(body, severities, quiet=quiet)


def report_invalid_target(target: str) -> list:
    return get_basic_header_and_text_blocks(
        header_text=f"{target} was not recognised",
        texts=f"Run `@{settings.SLACK_APP_USERNAME} security usage` to see the valid values for `target`.",
    )


def report_invalid_list_of_targets() -> list:
    return get_basic_header_and_text_blocks(
        header_text="Invalid list of targets",
        texts="List items must all be teams, all be orgs, or all be repos.",
    )


def main(args) -> str:
    severities = ALL_SEVERITIES if args.all_severities else DEFAULT_SEVERITIES
    try:
        blocks = _main(args.target, severities=severities, quiet=args.quiet)
    except Exception as e:
        blocks = get_basic_header_and_text_blocks(
            header_text=f"An error occurred reporting security alerts for {' '.join(args.target)}",
            texts=str(e),
        )
    if not blocks:
        return ""
    return json.dumps(blocks)


def _main(targets: list[str], severities: list[str], quiet: bool = False) -> list:
    """
    Build the response blocks. Returns an empty list when there is nothing to
    report and quiet=True (which the caller serialises as empty stdout so the
    dispatcher can skip posting).

    Targets may be:
      - "all": summarise all teams
      - team shorthand (e.g. "rap") - full team names with spaces are not supported
        because the parser splits on whitespace
      - known repo name (org optional)
      - org shorthand or full org name
      - "org/repo" string

    Multiple targets must be of the same type (all teams, all orgs, or all repos).
    """
    if "all" in targets:
        return summarise_all(severities, quiet=quiet)

    # Each target is sorted into one of three groups. Mixing types in one
    # invocation is rejected below.
    teams: list[str] = []
    orgs: list[str] = []
    repo_full_names: list[str] = []

    team_shorthands = config.team_shorthands()
    org_shorthands = config.org_shorthands()
    for target in targets:
        # Some repos are names of websites and Slack auto-linkifies them by prepending
        # http:// (or https:// for some domains)
        target = target.removeprefix("http://").removeprefix("https://")

        if target in team_shorthands:
            teams.append(team_shorthands[target])
            continue

        # More than one "/" can never be a valid org/repo (e.g. "a/b/c").
        if target.count("/") > 1:
            return report_invalid_target(target)

        if "/" in target:
            org, repo = target.split("/")
        elif matching_orgs := config.find_orgs_for_repo(target):
            org, repo = matching_orgs[0], target
        else:
            # No "/" and not a known short repo name - assume it's an org.
            org, repo = target, None

        org = org_shorthands.get(org, org)
        if org not in org_shorthands.values():
            return report_invalid_target(target)
        if repo:
            full_name = f"{org}/{repo}"
            if full_name in get_excluded_repos():
                return report_invalid_target(target)
            repo_full_names.append(full_name)
        else:
            orgs.append(org)

    # Reject mixed-type lists like `report rap osc` or `report osc airlock`;
    if sum(bool(x) for x in (teams, orgs, repo_full_names)) > 1:
        return report_invalid_list_of_targets()

    if teams:
        body: list = []
        for team in teams:
            body.extend(summarise_team(team, severities))
        return _wrap_with_top_header(body, severities, quiet=quiet)

    if orgs:
        body = []
        for org in orgs:
            body.extend(summarise_org(org, severities))
        return _wrap_with_top_header(body, severities, quiet=quiet)

    if len(repo_full_names) == 1:
        # Single-repo report doesn't go through _wrap_with_top_header (it has
        # its own header), so we need to handle the quiet-with-no-alerts case
        # explicitly here.
        reporter = RepoAlertsReporter(repo_full_names[0], severities=severities)
        if quiet and not any(reporter.get_counts().values()):
            return []
        return reporter.report_blocks()

    items = _repos_with_alerts(repo_full_names, severities)
    body = [
        get_summary_block(repo_full_name, counts, severities)
        for repo_full_name, counts in items
    ]
    return _wrap_with_top_header(body, severities, quiet=quiet)


def get_usage_text(args) -> str:
    orgs = ", ".join(f"`{k} ({v})`" for k, v in config.org_shorthands().items())
    teams = ", ".join(f"`{k} ({v})`" for k, v in config.team_shorthands().items())
    lines = [
        "Usage for `security report [target]`:",
        "`report`: Report open critical/high security alerts across all teams.",
        f"`report [team]`: Report open critical/high security alerts for a known team: {teams}.",
        f"`report [org]`: Report open critical/high security alerts for a known organisation: {orgs}.",
        "`report [repo]`:  Report open critical/high security alerts for a known repo (e.g. `report airlock`) or a repo in a known org (e.g. `report os/some-study-repo`).",
        "To pass multiple targets of the same type (org/team/repo), separate them by spaces.",
        "",
        "Use `check` / `check [target]` for the same outputs but with no Slack message when there are no alerts to report.",
        "Use `report-all` / `report-all [target]` to include medium and low severity alerts as well as critical and high.",
        "",
        "Repos monitored, by team:",
    ]
    for team in config.teams():
        repos = sorted(
            repo
            for repos_in_org in config.repos_by_org().values()
            for repo, repo_team in repos_in_org.items()
            if repo_team == team
        )
        lines.append(f"  - {team}: {', '.join(repos) if repos else '(none)'}")
    return "\n".join(lines)


def get_command_line_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True)

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument(
        "--target",
        default="all",
        action=SplitString,
        help="Provide multiple targets as a space-separated quoted string, e.g. 'osc ebm'.",
    )
    report_parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Emit empty output when there is nothing to report (for use with suppress_empty jobs).",
    )
    report_parser.add_argument(
        "--all-severities",
        action="store_true",
        default=False,
        help="Report on critical/high/medium/low alerts instead of only critical/high.",
    )
    report_parser.set_defaults(func=main)

    usage_parser = subparsers.add_parser("usage")
    usage_parser.set_defaults(func=get_usage_text)

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
