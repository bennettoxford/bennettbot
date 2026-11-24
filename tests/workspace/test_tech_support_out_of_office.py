import json
from unittest.mock import patch

import pytest

from workspace.techsupport.jobs import (
    out_of_office_off,
    out_of_office_on,
    out_of_office_status,
)


@pytest.fixture
def config_path(tmp_path):
    yield tmp_path / "test_ooo.json"


@pytest.mark.parametrize(
    "config,message",
    [
        (None, "Tech support out of office OFF"),  # OOO not on
        (
            {"start": "2022-01-01", "end": "3033-01-01"},  # OOO on
            "Tech support out of office OFF",
        ),
        (
            {"start": "3033-01-01", "end": "3033-01-01"},  # OOO scheduled
            "Scheduled tech support out of office cancelled",
        ),
    ],
)
def test_out_of_office_off(config_path, config, message):
    if config is not None:
        with open(config_path, "w") as f_out:
            json.dump(config, f_out)
    with patch("workspace.techsupport.jobs.config_file", return_value=config_path):
        assert out_of_office_off() == message


@pytest.mark.parametrize(
    "config,message",
    [
        (None, "Tech support out of office is currently OFF."),  # OOO not on
        (
            {"start": "2000-01-01", "end": "2001-01-01"},  # OOO past
            "Tech support out of office is currently OFF.",
        ),
        (
            {"start": "2022-01-01", "end": "3033-01-01"},  # OOO on
            "Tech support out of office is currently ON until 3033-01-01.",
        ),
        (
            {"start": "3033-01-01", "end": "3033-01-01"},  # OOO scheduled
            "Tech support out of office is currently OFF.\n"
            "Scheduled out of office is from 3033-01-01 until 3033-01-01.",
        ),
    ],
)
def test_out_of_office_status(config_path, config, message):
    if config is not None:
        with open(config_path, "w") as f_out:
            json.dump(config, f_out)
    with patch("workspace.techsupport.jobs.config_file", return_value=config_path):
        assert out_of_office_status() == message


@pytest.mark.parametrize(
    "start,end,message",
    [
        (
            "2020-12-01",
            "3033-12-01",
            "Tech support out of office now ON until 3033-12-01",
        ),
        (
            "3033-12-01",
            "3034-12-01",
            "Tech support out of office scheduled from 3033-12-01 until 3034-12-01",
        ),
    ],
)
def test_out_of_office_on(config_path, start, end, message):
    assert not config_path.exists()
    with patch("workspace.techsupport.jobs.config_file", return_value=config_path):
        assert out_of_office_on(start, end) == message
    assert config_path.exists()
    with open(config_path) as f_in:
        config = json.load(f_in)
    assert config == {"start": start, "end": end}


@pytest.mark.parametrize(
    "start,end,message",
    [
        # trying to set OOO in the past
        ("2020-12-01", "2020-12-02", "Error: Can't set out of office in the past"),
        # start date after end date
        ("3033-12-01", "3033-11-01", "Error: start date must be before end date"),
    ],
)
def test_out_of_office_on_errors(config_path, start, end, message):
    assert not config_path.exists()
    with patch("workspace.techsupport.jobs.config_file", return_value=config_path):
        assert out_of_office_on(start, end) == message
    assert not config_path.exists()


@pytest.mark.parametrize(
    "start,end",
    [
        ("2020-02-30", "2020-12-02"),  # bad start
        ("3033-12-01", "3033-13-01"),  # bad end
    ],
)
def test_out_of_office_on_invalid_dates(config_path, start, end):
    assert not config_path.exists()
    with patch("workspace.techsupport.jobs.config_file", return_value=config_path):  # noqa: SIM117
        with pytest.raises(ValueError):
            out_of_office_on(start, end)
    assert not config_path.exists()
