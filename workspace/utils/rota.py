import abc
import json
from datetime import date, timedelta
from itertools import cycle, islice
from pathlib import Path

from bennettbot import settings
from workspace.utils.blocks import (
    get_basic_header_and_text_blocks,
    get_run_command_button_block,
)
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
    """One candidate per calendar week, anchored to `weekday` (0=Monday,
    ..., 6=Sunday - same numbering as `date.weekday()`), which defaults to
    Monday.

    Uses the ISO week number directly rather than NWeeklyCadence(weeks=1)'s
    start_date-counting, since a single calendar week is already a stable,
    globally meaningful index on its own and doesn't need an anchor date.
    """

    def __init__(self, weekday: int = 0):
        self.weekday = weekday

    def interval_index(self, interval_start: date) -> int:
        return interval_start.isocalendar().week

    def interval_start(self, d: date) -> date:
        return d - timedelta(days=(d.weekday() - self.weekday) % 7)

    def next_interval_start(self, interval_start: date) -> date:
        return interval_start + timedelta(weeks=1)


class NWeeklyCadence:
    """One candidate every N calendar weeks, anchored to `start_date`.

    Interval boundaries fall every N weeks from `start_date`, on
    whatever weekday `start_date` itself is.

    A date before `start_date` (e.g. calling the rota to see who's coming
    up before the rota's gone live, or before the first scheduled run)
    still maps to the first interval, rather than counting backwards into
    a notional earlier cycle.
    """

    def __init__(self, weeks: int, start_date: date):
        self.weeks = weeks
        self.start_date = start_date

    def interval_index(self, interval_start: date) -> int:
        return (interval_start - self.start_date).days // (7 * self.weeks)

    def interval_start(self, d: date) -> date:
        # Clamp to 0 so a date before start_date lands in the first
        # interval instead of floor-dividing to a negative block number.
        days_since_start = max((d - self.start_date).days, 0)
        block = days_since_start // (7 * self.weeks)
        return self.start_date + timedelta(weeks=self.weeks * block)

    def next_interval_start(self, interval_start: date) -> date:
        return interval_start + timedelta(weeks=self.weeks)


class MonthlyCadence:
    """One candidate per calendar month, anchored to `day_of_month`.

    `day_of_month` is restricted to 1-28, to avoid having to handle short
    months or leap years.
    """

    def __init__(self, day_of_month: int = 1):
        if not 1 <= day_of_month <= 28:
            raise ValueError("day_of_month must be between 1 and 28")
        self.day_of_month = day_of_month

    @staticmethod
    def interval_index(interval_start: date) -> int:
        return interval_start.year * 12 + interval_start.month

    def interval_start(self, d: date) -> date:
        # Before day_of_month, d belongs to the interval that started last
        # month, not this one, so we need to shift the current month back 1.
        if d.day < self.day_of_month:
            d = self._shift_months(d, -1)
        return date(d.year, d.month, self.day_of_month)

    def next_interval_start(self, interval_start: date) -> date:
        # Note that the date we're shifting from here is `interval_start` and
        # is already day_of_month-anchored (not an arbitrary date or "today").
        shifted = self._shift_months(interval_start, 1)
        return date(shifted.year, shifted.month, self.day_of_month)

    @staticmethod
    def _shift_months(d: date, months: int) -> date:
        # Flatten (year, month) from the supplied date into a single zero-based
        # month count, so shifting by any number of months - including rolling over a
        # year boundary - is just integer addition
        month_index = d.year * 12 + (d.month - 1) + months
        # divmod() splits the count back into (year, 0-based month);
        # +1 undoes the zero-basing.
        year, month = divmod(month_index, 12)
        return date(year, month + 1, 1)


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
        advance_command: str | None = None,
    ):
        super().__init__(title)
        self.candidates = candidates
        self.state_key = state_key
        self.cadence = cadence
        self.advance_command = advance_command

    def _advance_footnote_block(self) -> dict | None:
        """An "Advance the rota" button, shown after the report when
        `advance_command` is set - e.g. for when the person on duty isn't
        available. Clicking it runs `advance_command` exactly as if the
        user had typed it."""
        if not self.advance_command:
            return None
        return get_run_command_button_block(
            button_text="Not available? Advance the rota",
            command=self.advance_command,
        )

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
        return f"Rota advanced: {checker.formatted_slack_username} is now on {duty}."

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

        texts = [
            self.get_rota_text_for_interval(rota, this_interval, this_or_next="this"),
            self.get_rota_text_for_interval(rota, next_interval, this_or_next="next"),
            *extra_texts,
        ]
        blocks = get_basic_header_and_text_blocks(header_text=self.title, texts=texts)

        footnote_block = self._advance_footnote_block()
        if footnote_block:
            blocks.append(footnote_block)

        return json.dumps(blocks, indent=2)
