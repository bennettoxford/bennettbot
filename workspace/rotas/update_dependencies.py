import argparse
import json
from urllib.parse import quote_plus

from workspace.utils import repos_config
from workspace.utils.blocks import (
    get_basic_header_and_text_blocks,
    get_fields_blocks,
    get_text_block,
)
from workspace.utils.people import team_members
from workspace.utils.rota import RollingRotaReporter


# Optional custom notes for the report, specific to individual teams.
TEAM_NOTES = {
    "Team RAP": (
        "Here's a reminder of what you need to do:\n"
        "  • review the update-dependencies PRs that appear in "
        "#team-rap-code-reviews\n"
        "  • check each repo for open Dependabot/Renovate PRs for "
        "dependency and security updates\n"
        "  • check each repo for vulnerabilities and address"
    ),
}


class UpdateDependenciesReporter(RollingRotaReporter):
    def __init__(
        self,
        team_name: str,
        repos: list[str] | None = None,
        notes: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.team_name = team_name
        self.repos = repos or []
        self.notes = notes

    def get_rota_text_for_interval(self, rota, interval_start, this_or_next):
        checker = rota[interval_start]
        if this_or_next == "this":
            checker = checker.formatted_slack_username
        else:
            checker = checker.human_readable
        return (
            f"On duty {this_or_next} week "
            f"({self.format_interval(interval_start)}): {checker}"
        )

    def report(self, *extra_texts):
        rota = self.get_rota()
        this_interval, next_interval = sorted(rota)
        # One block for both lines to reduce vertical space.
        duty_text = "\n".join(
            [
                self.get_rota_text_for_interval(rota, this_interval, "this"),
                self.get_rota_text_for_interval(rota, next_interval, "next"),
            ]
        )

        blocks = get_basic_header_and_text_blocks(
            header_text=self.title,
            texts=[duty_text, self._all_open_prs_link_text()],
        )
        blocks.extend(self._repo_link_field_blocks())
        blocks.extend(get_text_block(text) for text in extra_texts)

        if self.notes:
            blocks.append(get_text_block(self.notes))

        return json.dumps(blocks, indent=2)

    def _all_open_prs_link_text(self) -> str:
        """Generate a combined "All open PRs" search link, filtered to just dependency-labelled PRs."""
        repo_query = " OR ".join(f"repo:{full_name}" for full_name in self.repos)
        combined_link = "https://github.com/pulls?q=" + quote_plus(
            f"is:pr is:open ({repo_query}) label:dependencies"
        )
        return f"<{combined_link}|All open PRs>"

    def _repo_link_field_blocks(self) -> list[dict]:
        """
        Links to each repo, laid out as Slack
        "fields" grid blocks.
        """
        fields = [
            f"• <https://github.com/{full_name}/pulls|{full_name}>"
            for full_name in self.repos
        ]
        return get_fields_blocks(fields)


def _slugify_team_name(team_name: str) -> str:
    return team_name.lower().replace(" ", "-")


def _build_reporter(
    team_name: str, repos: list[str] | None = None
) -> UpdateDependenciesReporter:
    return UpdateDependenciesReporter(
        title=f"{team_name} update-dependencies rota",
        candidates=team_members(team_name),
        state_key=f"{_slugify_team_name(team_name)}-update-dependencies",
        team_name=team_name,
        repos=repos,
        notes=TEAM_NOTES.get(team_name),
    )


def report_rota(team_name: str) -> str:
    repos = sorted(repos_config.get_repo_full_names_for_team(team_name))
    return _build_reporter(team_name, repos).report()


def advance_rota(team_name: str) -> str:
    return _build_reporter(team_name).advance("update-dependencies")


def now_rota(team_name: str) -> str:
    return _build_reporter(team_name).now("update-dependencies")


def get_command_line_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--team", required=True, help='Team name, e.g. "Team RAP"')
    subparsers = parser.add_subparsers(dest="subparser_name", required=True)

    rota_parser = subparsers.add_parser("rota")
    rota_parser.set_defaults(function=report_rota)

    advance_parser = subparsers.add_parser("advance")
    advance_parser.set_defaults(function=advance_rota)

    now_parser = subparsers.add_parser("now")
    now_parser.set_defaults(function=now_rota)

    return parser


if __name__ == "__main__":
    args = get_command_line_parser().parse_args()
    print(args.function(args.team))
