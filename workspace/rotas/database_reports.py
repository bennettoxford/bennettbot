import argparse
import json
from datetime import date, timedelta

from workspace.utils.blocks import get_basic_header_and_text_blocks
from workspace.utils.people import team_members
from workspace.utils.rota import NWeeklyCadence, RollingRotaReporter


TEAM_NAME = "Team RAP"
STATE_KEY = "team-rap-database-reports"
ADVANCE_COMMAND = "rotas database-reports advance"

# The 4-weekly cycle's first real interval.
START_DATE = date(2026, 11, 5)  # a Thursday, the week after the expected DB build

NOTES = (
    "The database build should have started last Friday; check that we are "
    "in maintenance mode (or that the build has finished) before running "
    "the reports.\n"
    "  • <https://jobs.opensafely.org/opensafely-internal/tpp-database-schema/"
    "|tpp-database-schema>\n"
    "  • <https://jobs.opensafely.org/opensafely-internal/tpp-database-history/"
    "|tpp-database-history>\n"
    "  • <https://jobs.opensafely.org/opensafely-internal/tpp-database-import-dates/"
    "|tpp-database-import-dates>\n\n"
    "Remember to <https://bennett.wiki/tech-group/playbooks/"
    "opensafely-tpp-database-reports/|publish the files and update the "
    "reports site> when the files have been released."
)


class DatabaseReportsReporter(RollingRotaReporter):
    def get_rota_text_for_interval(self, rota, interval_start, this_or_next):
        checker = rota[interval_start]
        interval_end = self.cadence.next_interval_start(interval_start) - timedelta(
            days=1
        )
        date_range = (
            f"{interval_start.strftime('%d %b')}-{interval_end.strftime('%d %b')}"
        )
        return f"{checker.formatted_slack_username} is on duty ({date_range})"

    def report(self, *extra_texts):
        # Just show who's on duty now.
        rota = self.get_rota()
        this_interval = self.cadence.interval_start(date.today())
        duty_text = self.get_rota_text_for_interval(rota, this_interval, "this")

        blocks = get_basic_header_and_text_blocks(
            header_text=self.title,
            texts=[duty_text, NOTES, *extra_texts],
        )

        if footnote_block := self._advance_footnote_block():
            blocks.append(footnote_block)

        return json.dumps(blocks, indent=2)


def _build_reporter() -> DatabaseReportsReporter:
    return DatabaseReportsReporter(
        title=f"{TEAM_NAME} Database Reports",
        candidates=team_members(TEAM_NAME),
        state_key=STATE_KEY,
        cadence=NWeeklyCadence(weeks=4, start_date=START_DATE),
        advance_command=ADVANCE_COMMAND,
    )


def report_rota() -> str:
    return _build_reporter().report()


def advance_rota() -> str:
    return _build_reporter().advance("database-reports")


def now_rota() -> str:
    return _build_reporter().now("database-reports")


def get_command_line_parser():
    parser = argparse.ArgumentParser()
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
    print(args.function())
