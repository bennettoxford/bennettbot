from datetime import date, timedelta
from itertools import cycle, islice

from workspace.utils.people import TEAM_REX, People
from workspace.utils.rota import RotaReporter


class DependabotRotaReporter(RotaReporter):
    """
    This implements a stateless rolling rota of candidates.
    The candidates are currently Team Rex (except Katie).
    If the candidate definition or Team changes this will affect
    the rota offset and the rota will restart at an arbitrary point.
    """

    def get_rota(self) -> dict:
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        next_monday = this_monday + timedelta(weeks=1)

        candidates = [r for r in TEAM_REX if r != People.KATIE]
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
    return DependabotRotaReporter(
        title="Dependabot rota",
    ).report(
        "\nReview "
        "<https://github.com/opensafely-core/job-server/pulls|job-server>, "
        "<https://github.com/opensafely-core/opencodelists/pulls|opencodelists>, "
        "<https://github.com/ebmdatalab/metrics/pulls|metrics>, "
        "<https://github.com/opensafely-core/reports/pulls|reports>, "
        "<https://github.com/opensafely-core/actions-registry/pulls|actions-registry> and "
        "<https://github.com/opensafely-core/research-template-docker/pulls|research-template-docker> "
        "repos and merge any outstanding non-NPM Dependabot/update-dependencies-action PRs.\n"
        "Review Thomas' PRs for NPM updates.\n"
    )


if __name__ == "__main__":
    print(report_rota())
