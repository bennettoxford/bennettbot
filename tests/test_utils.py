import argparse

from workspace.utils.argparse import SplitString
from workspace.utils.blocks import truncate_text


def test_truncate_text():
    original_text = "hello" * 1000
    truncated_text = truncate_text(original_text)
    assert len(truncated_text) == 3000
    assert truncated_text.endswith("...")


def test_split_string():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--values",
        action=SplitString,
        help="A space-separated quoted string",
    )
    args = parser.parse_args(["--values", "value1 value2 value3"])
    assert args.values == ["value1", "value2", "value3"]
