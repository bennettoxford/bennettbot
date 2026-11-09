import pytest

from workspace.utils import blocks


@pytest.mark.parametrize(
    "style,expected_button_extra",
    [
        (None, {}),
        ("primary", {"style": "primary"}),
    ],
)
def test_get_run_command_button_block(style, expected_button_extra):
    block = blocks.get_run_command_button_block(
        button_text="Click me", command="namespace do the thing", style=style
    )

    assert block == {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Click me"},
                "action_id": blocks.RUN_COMMAND_BUTTON_ACTION_ID,
                "value": "namespace do the thing",
                **expected_button_extra,
            }
        ],
    }
