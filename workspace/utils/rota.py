import abc
import json
from datetime import date, timedelta
from itertools import cycle, islice
from pathlib import Path

from bennettbot import settings
from workspace.utils.blocks import get_basic_header_and_text_blocks
from workspace.utils.spreadsheets import get_data_from_sheet


class RotaReporter(abc.ABC):
    def __init__(self, title: str):
        self.title = title

    def report(self, *extra_texts):
        rota = self.get_rota()

        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        next_monday = this_monday + timedelta(days=7)

        blocks = get_basic_header_and_text_blocks(
            header_text=self.title,
            texts=[
                self.get_rota_text_for_interval(rota, this_monday, this_or_next="this"),
                self.get_rota_text_for_interval(rota, next_monday, this_or_next="next"),
                *extra_texts,
            ],
        )
        return json.dumps(blocks, indent=2)

    @abc.abstractmethod
    def get_rota(self) -> dict:
        """
        Gets the rota from source
        """

    @abc.abstractmethod
    def get_rota_text_for_interval(
        self, rota: dict, interval_start: date, this_or_next: str
    ) -> str:
        """
        Returns plain text reporting either the rota or a message saying no rota data was found
        """

    @staticmethod
    def format_interval(interval_start: date):
        friday = interval_start + timedelta(days=4)  # Work week
        return f"{interval_start.strftime('%d %b')}-{friday.strftime('%d %b')}"


class SpreadsheetRotaReporter(RotaReporter):
    def __init__(self, title: str, spreadsheet_id: str, sheet_range: str):
        super().__init__(title)
        self.spreadsheet_id = spreadsheet_id
        self.sheet_range = sheet_range

    def get_rota_data_from_sheet(self):  # pragma: no cover
        return get_data_from_sheet(self.spreadsheet_id, self.sheet_range)

    def report(self, *extra_texts):
        return RotaReporter.report(
            self,
            self.get_text_linking_rota_spreadsheet(),
        )

    def get_rota(self):
        rows = self.get_rota_data_from_sheet()
        rows = [[v.strip() for v in row] for row in rows]
        rota = self.convert_rota_data_to_dictionary(rows)
        return rota

    @abc.abstractmethod
    def convert_rota_data_to_dictionary(self, rows) -> dict:
        """
        Takes the rows returned from get_rota_data_from_sheet and converts them into a dictionary with dates as keys
        """

    def get_text_linking_rota_spreadsheet(self):
        return f"<https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}|Open rota spreadsheet>"


class WeeklyCadence:
    """One candidate per calendar week, Monday-anchored.

    The only cadence RollingRotaReporter currently supports. A future
    4-weekly or monthly cadence would be a different class with the same
    three methods.
    """

    @staticmethod
    def interval_index(interval_start: date) -> int:
        return interval_start.isocalendar().week

    @staticmethod
    def interval_start(d: date) -> date:
        return d - timedelta(days=d.weekday())

    @staticmethod
    def next_interval_start(interval_start: date) -> date:
        return interval_start + timedelta(weeks=1)


class RollingRotaReporter(RotaReporter):
    """
    A rolling rota that picks a candidate for the current and next interval
    from `candidates`, based on a calendar-derived index. A persisted offset,
    adjustable via `advance()`, shifts that pick forward (e.g. when the person
    who'd be on duty isn't available), without losing the calendar-derived
    schedule for later.

    Passes `this_or_next="this"`/`"next"` to get_rota_text_for_interval, same
    as RotaReporter.report() does. But since the cadence needn't be weekly,
    subclasses shouldn't assume "this week"/"next week" makes sense - how
    `this_or_next` gets worded for a given cadence is up to each subclass.
    """

    def __init__(
        self,
        title: str,
        candidates: list,
        state_key: str,
        cadence=WeeklyCadence(),
    ):
        super().__init__(title)
        self.candidates = candidates
        self.state_key = state_key
        self.cadence = cadence

    def _state_path(self) -> Path:
        return settings.WRITEABLE_DIR / "rota_state" / f"{self.state_key}.json"

    def _read_offset(self) -> int:
        path = self._state_path()
        if not path.exists():
            return 0
        return json.loads(path.read_text())["offset"]

    def _write_offset(self, offset: int) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"offset": offset}))

    def advance(self, duty_name: str | None = None) -> str:
        """
        Shift the whole rota forward by one candidate. Returns a
        confirmation naming who's now on duty.
        """
        self._write_offset(self._read_offset() + 1)

        this_interval = self.cadence.interval_start(date.today())
        checker = self.get_rota()[this_interval]
        duty = f"{duty_name} duty" if duty_name else "duty"
        return f"Rota advanced: {checker.human_readable} is now on {duty}."

    def now(self, duty_name: str | None = None) -> str:
        """
        Returns a short plain-text message naming who's on duty for the
        current interval, without rendering the full report.
        """
        this_interval = self.cadence.interval_start(date.today())
        checker = self.get_rota()[this_interval]
        duty = f"{duty_name} duty" if duty_name else "duty"
        return f"{checker.human_readable} is on {duty}."

    def get_rota(self) -> dict:
        this_interval = self.cadence.interval_start(date.today())
        next_interval = self.cadence.next_interval_start(this_interval)

        offset = self._read_offset()
        index = (self.cadence.interval_index(this_interval) + offset) % len(
            self.candidates
        )

        # allow looping around the end of the list in case index+1==len(candidates)
        candidates = islice(cycle(self.candidates), index, None)

        return {
            this_interval: next(candidates),
            next_interval: next(candidates),
        }

    def report(self, *extra_texts):
        rota = self.get_rota()
        this_interval, next_interval = sorted(rota)

        blocks = get_basic_header_and_text_blocks(
            header_text=self.title,
            texts=[
                self.get_rota_text_for_interval(
                    rota, this_interval, this_or_next="this"
                ),
                self.get_rota_text_for_interval(
                    rota, next_interval, this_or_next="next"
                ),
                *extra_texts,
            ],
        )
        return json.dumps(blocks, indent=2)
