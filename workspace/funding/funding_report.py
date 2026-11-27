import json
from datetime import UTC, datetime

from workspace.utils.blocks import get_header_block, get_text_block
from workspace.utils.spreadsheets import get_data_from_sheet


funding_spreadsheet_id = "18xM7nu1aD9dZe-eJbqrIRxinO5tjSBZv0EpJRlvz_BI"


def main():
    rows = get_data_from_sheet(
        spreadsheet_id=funding_spreadsheet_id,
        sheet_range="Calls",
    )

    headers = rows[0]
    rows = [dict(zip(headers, row)) for row in rows[1:]]

    calls_recently_added = []
    calls_closing_soon = []

    for row in rows:
        opportunity = row["Opportunity"]
        funder = row["Funder(s)"]
        type_ = row["Type"]
        link = row["Link (specific call)"] or row["Link (general funding stream)"]

        award = row["Max award (£)"]
        if not award.strip():  # pragma: no cover
            award = "£ Not stated"
        elif award.isnumeric():  # pragma: no cover
            award = f"£{int(award):,}"

        added_date = row["Added/updated date"]
        if not added_date:  # pragma: no cover
            continue
        added_date = datetime.strptime(added_date, "%d %b %Y").astimezone(UTC).date()
        days_since_added = (datetime.now(tz=UTC).date() - added_date).days

        deadline_date = row["Deadline / expression of interest date"]
        if not deadline_date:  # pragma: no cover
            continue
        try:
            deadline_date = (
                datetime.strptime(deadline_date, "%d %b %Y").astimezone(UTC).date()
            )
            days_to_deadline = (deadline_date - datetime.now(tz=UTC).date()).days
        except ValueError:
            deadline_date = f"unknown date: {deadline_date}"
            days_to_deadline = 0

        if days_since_added <= 14:  # pragma: no branch
            line = f"{type_}: <{link}|{opportunity}>, ({funder}, {award})"
            calls_recently_added.append(
                {
                    "type": type_,
                    "deadline_date": deadline_date,
                    "line": line,
                }
            )

        if days_to_deadline <= 30:  # pragma: no branch
            line = f"{type_}: <{link}|{opportunity}>, ({funder}, {award}), closing {deadline_date} ({days_to_deadline} days)"
            calls_closing_soon.append(
                {
                    "type": type_,
                    "deadline_date": deadline_date,
                    "line": line,
                }
            )

    types = ["Project", "Programme", "Fellowship", "PhD", "Infrastructure", "Other"]

    calls_recently_added.sort(
        key=lambda row: (types.index(row["type"]), str(row["deadline_date"]))
    )
    calls_closing_soon.sort(
        key=lambda row: (types.index(row["type"]), str(row["deadline_date"]))
    )

    blocks = [get_header_block(":moneybag: *Funding update* :moneybag:")]

    if calls_recently_added:  # pragma: no branch
        blocks.extend(
            [
                {"type": "divider"},
                get_text_block("*Recently added calls*"),
            ]
        )

        for call in calls_recently_added:
            blocks.append(get_text_block(call["line"]))

    if calls_closing_soon:  # pragma: no branch
        blocks.extend(
            [
                {"type": "divider"},
                get_text_block("*Calls closing within 30 days*"),
            ]
        )

        for call in calls_closing_soon:
            blocks.append(get_text_block(call["line"]))

    blocks.extend(
        [
            {"type": "divider"},
            get_text_block(
                f"Further details for all funding opportunities are available on the <https://docs.google.com/spreadsheets/d/{funding_spreadsheet_id}/|funding tracker>."
            ),
        ]
    )

    if len(blocks) > 50:  # pragma: no cover
        blocks = blocks[0:48]
        blocks.extend(
            [
                {"type": "divider"},
                get_text_block(
                    f"*Report truncated* - further details for all funding opportunities are available on the <https://docs.google.com/spreadsheets/d/{funding_spreadsheet_id}/|funding tracker>."
                ),
            ]
        )
    return json.dumps(blocks, indent=2)


if __name__ == "__main__":
    print(main())
