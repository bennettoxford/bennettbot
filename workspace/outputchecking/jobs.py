from datetime import date

from workspace.utils.rota import SpreadsheetRotaReporter


class OutputCheckingRotaReporter(SpreadsheetRotaReporter):
    def convert_rota_data_to_dictionary(self, rows) -> dict:
        return {row[0]: (row[1], row[2]) for row in rows[1:] if len(row) >= 3}

    def get_rota_text_for_week(self, rota: dict, monday: date, this_or_next: str):
        try:
            primary, secondary = rota[str(monday)]
            return f"Lead reviewer {this_or_next} week ({self.format_week(monday)}): {primary} (secondary: {secondary})"
        except KeyError:
            return f"No rota data found for {this_or_next} week"


def report_rota():
    return OutputCheckingRotaReporter(
        title="Output checking rota",
        spreadsheet_id="1i3D_HtuYUCU_dqvRug94YkfK6pG4ECyxTdOangubUlY",
        sheet_range="Rota 2026",
    ).report()


if __name__ == "__main__":
    print(report_rota())
