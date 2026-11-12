def get_text_block(text, block_type="section", text_type="mrkdwn"):
    return {
        "type": block_type,
        "text": {
            "type": text_type,
            "text": text,
        },
    }


def get_header_block(header_text, text_type="plain_text"):
    return get_text_block(header_text, block_type="header", text_type=text_type)


# action_id for a button that runs a bot command - bennettbot.bot registers a
# single Slack action listener for this id, which runs the clicked button's
# `value` (a bot command string, e.g. "rotas rap-dependencies advance")
# exactly as if the user had typed it. Any report can add a button for an
# existing command this way - e.g. a rota's "advance" button, or (in future)
# buttons on a job-failure report that run "showlogs head/tail/all".
RUN_COMMAND_BUTTON_ACTION_ID = "run_bot_command"


def get_run_command_button_element(
    button_text: str,
    command: str,
    style=None,
    action_id=RUN_COMMAND_BUTTON_ACTION_ID,
    id_suffix=None,
):
    """
    A single button element, which runs a slack command, for embedding within an
    actions block.

    `style` can be "primary" (green) or "danger" (red) to make the button
    stand out; omit it for Slack's default (neutral) styling.

    Elements within the same block must have unique action_ids; pass a
    (lowercase alphanumeric) suffix to differentiate this button if using more
    than one in a block.
    """
    if id_suffix is not None:
        action_id = f"{action_id}_{id_suffix}"
    button = {
        "type": "button",
        "text": {"type": "plain_text", "text": button_text},
        "action_id": action_id,
        "value": command,
    }
    if style:
        button["style"] = style
    return button


def get_run_command_button_block(
    button_text: str,
    command: str,
    style=None,
    action_id=RUN_COMMAND_BUTTON_ACTION_ID,
    id_suffix=None,
):
    """An "actions" block with one button element, which runs
    `command` - a full bot command as if the user had typed it.
    """
    button = get_run_command_button_element(
        button_text, command, style, action_id, id_suffix
    )
    return get_actions_block([button])


def get_actions_block(elements: list[dict]) -> dict:
    """Return a Slack actions block containing the given action elements."""
    return {
        "type": "actions",
        "elements": elements,
    }


def get_basic_header_and_text_blocks(
    header_text: str, texts: list | str, text_type="mrkdwn"
):
    """
    Returns a list of blocks: a header block and text blocks with little room for customization.
    "texts" can be a list of strings or a single string; In the former case, each string will be a separate text block.
    The header block is a plain text header block.
    The text blocks have block type "section" and the text type is "mrkdwn" by default.
    """
    header_block = get_header_block(header_text)
    if isinstance(texts, str):
        texts = [texts]
    if len(texts) > 49:  # pragma: no cover
        raise ValueError(
            f"""Slack has a limit of 50 blocks per message. Currently there are {len(texts) + 1} blocks including the header block."""
        )
    text_blocks = [get_text_block(text, text_type=text_type) for text in texts]
    return [header_block] + text_blocks


# Slack caps a section block's "fields" grid at this many items.
MAX_FIELDS_PER_BLOCK = 10


def get_fields_blocks(fields: list[str], text_type="mrkdwn") -> list[dict]:
    """
    `fields` laid out as Slack's native 2-column "fields" grid (fields fill
    left-to-right, top-to-bottom), split across as many section blocks as
    needed to stay within Slack's limit of MAX_FIELDS_PER_BLOCK.
    """
    return [
        {
            "type": "section",
            "fields": [
                {"type": text_type, "text": field}
                for field in fields[i : i + MAX_FIELDS_PER_BLOCK]
            ],
        }
        for i in range(0, len(fields), MAX_FIELDS_PER_BLOCK)
    ]


def get_ambiguous_target_blocks(target: str, orgs: list[str]) -> list:
    """Header + body explaining that a bare repo name maps to multiple known orgs."""
    options = ", ".join(f"`{org}/{target}`" for org in sorted(orgs))
    return get_basic_header_and_text_blocks(
        header_text=f"{target} is ambiguous",
        texts=f"Multiple known orgs have a repo called `{target}`. Please specify one of: {options}.",
    )


def truncate_text(text, max_len=3000):
    # Slack has a limit of 3000 characters per text block
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text
