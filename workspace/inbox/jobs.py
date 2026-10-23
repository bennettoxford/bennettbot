from datetime import date

from workspace.utils.rota import SpreadsheetRotaReporter


class InboxRotaReporter(SpreadsheetRotaReporter):
    def convert_rota_data_to_dictionary(self, rows) -> dict:
        return {row[0]: row[1] for row in rows[1:] if len(row) >= 2}

    def get_rota_text_for_interval(self, rota: dict, monday: date, this_or_next: str):
        try:
            researcher = rota[str(monday)]
            return f"Researcher {this_or_next} week ({self.format_interval(monday)}): {researcher}"
        except KeyError:
            return f"No rota data found for {this_or_next} week"


def report_rota():
    return InboxRotaReporter(
        title="Inbox rota (team@opensafely.org)",
        spreadsheet_id="1Z50ektmaOV-H78sC__hmyH2l5HAmPsIslZYYUfT3UWU",
        sheet_range="Rota 2025",
    ).report()


if __name__ == "__main__":
    print(report_rota())
