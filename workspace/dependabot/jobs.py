from datetime import date, timedelta
from itertools import cycle, islice

from workspace.utils.people import TEAM_REX
from workspace.utils.rota import RotaReporter


class DependabotRotaReporter(RotaReporter):
    """
    This implements a stateless rolling rota of candidates.
    The candidates are currently Team Rex.
    If the candidate definition or Team changes this will affect
    the rota offset and the rota will restart at an arbitrary point.
    Consider redesigning class to include an offset if that happens.
    """

    def get_rota(self) -> dict:
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        next_monday = this_monday + timedelta(weeks=1)

        candidates = [r for r in TEAM_REX]
        i = this_monday.isocalendar().week % len(candidates)

        # allow looping around the end of the list in case i+1==len(candidates)
        candidates = cycle(candidates)

        # offset the start of the loop such that it's a different person each week
        candidates = islice(candidates, i, None)

        return {
            this_monday: next(candidates),
            next_monday: next(candidates),
        }

    def get_rota_text_for_week(
        self, rota: dict, monday: date, this_or_next: str
    ) -> str:
        checker = rota[monday]
        if this_or_next == "this":
            checker = checker.formatted_slack_username
        else:
            checker = checker.human_readable
        return f"To review dependabot PRs {this_or_next} week ({self.format_week(monday)}): {checker}"


def report_rota() -> str:
    repos = [
        ("opensafely-core", "job-server"),
        ("opensafely-core", "opencodelists"),
        ("ebmdatalab", "metrics"),
        ("opensafely-core", "reports"),
        ("opensafely-core", "actions-registry"),
        ("opensafely-core", "research-template-docker"),
        ("opensafely-core", "repo-template"),
        ("opensafely", "documentation"),
    ]
    repo_links = [
        f"<https://github.com/{org}/{repo}/pulls|{repo}>" for org, repo in repos
    ]
    combined_link = "https://github.com/pulls?q=is%3Apr+is%3Aopen+" + "+".join(
        f"repo%3A{org}%2F{repo}" for org, repo in repos
    )

    repo_links_text = ", ".join(repo_links[:-1]) + " and " + repo_links[-1]
    extra_text = (
        f"\nReview repos {repo_links_text}. <{combined_link}|Combined link>. "
        "Merge any outstanding non-NPM Dependabot/update-dependencies-action PRs.\n"
        "Review Thomas' PRs for NPM updates.\n"
    )

    return DependabotRotaReporter(title="Dependabot rota").report(extra_text)


if __name__ == "__main__":
    print(report_rota())
