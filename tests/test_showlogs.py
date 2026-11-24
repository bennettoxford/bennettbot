import subprocess
from os import environ
from pathlib import Path

import pytest

from bennettbot import settings

from .test_dispatcher import build_log_dir


def setup_failed_logs(error="foo", output="bar"):
    log_dir = Path(build_log_dir("err_bad_job"))
    log_dir.mkdir(exist_ok=True, parents=True)
    with open(Path(log_dir) / "stderr", "w") as f:
        f.write(error)
    with open(Path(log_dir) / "stdout", "w") as f:
        f.write(output)
    return log_dir


@pytest.mark.parametrize(
    "option,logtype,expected_comment,expected_output",
    [
        ("-h", "error", b"Reading head of log file", b"foo"),
        ("-t", "error", b"Reading tail of log file", b"foo"),
        ("-g", "error", b"Invalid option", b""),
        ("-h", "output", b"Reading head of log file", b"bar"),
        ("-t", "output", b"Reading tail of log file", b"bar"),
        ("-g", "output", b"Invalid option", b""),
        ("-h", "unk", b"Error: invalid logtype 'unk'", b""),
        ("-t", "unk", b"Error: invalid logtype 'unk'", b""),
    ],
)
def test_logs(option, logtype, expected_comment, expected_output):
    log_dir = setup_failed_logs()
    logs_workspace = Path(__file__).parent.parent / "workspace" / "showlogs"

    rv = subprocess.run(
        f"/bin/bash show.sh {option} -f {logtype} {log_dir.resolve()}",
        cwd=logs_workspace,
        env={**environ, "PYTHONPATH": logs_workspace.parent},
        shell=True,
        capture_output=True,
        check=True,
    )
    assert expected_comment in rv.stdout
    assert expected_output in rv.stdout


def test_log_with_no_ouput():
    log_dir = setup_failed_logs(output="")
    logs_workspace = Path(__file__).parent.parent / "workspace" / "showlogs"

    rv = subprocess.run(
        f"/bin/bash show.sh -h -f output {log_dir.resolve()}",
        cwd=logs_workspace,
        env={**environ, "PYTHONPATH": logs_workspace.parent},
        shell=True,
        capture_output=True,
        check=True,
    )
    assert b"File has no content" in rv.stdout


def test_logs_with_different_host_logs_dir():
    log_dir = setup_failed_logs()
    logs_workspace = Path(__file__).parent.parent / "workspace" / "showlogs"

    # Log files are located at LOGS_DIR (in prod, a path to the logs folder in the
    # mounted volume). This is aliased to HOST_LOGS_DIR in slack messages, so that
    # failed commands tell users where to find logs on the host filesystem
    # So if a user calls the command with the host location, it needs to
    # look for the file in the real LOGS_DIR location
    dummy_host_logs = "/hosts/dummy_logs"
    host_log_dir = str(log_dir).replace(str(settings.LOGS_DIR), dummy_host_logs)

    rv = subprocess.run(
        f"/bin/bash show.sh -h -f error {host_log_dir}",
        cwd=logs_workspace,
        env={
            **environ,
            "PYTHONPATH": logs_workspace.parent,
            "LOGS_DIR": settings.LOGS_DIR.resolve(),
            "HOST_LOGS_DIR": dummy_host_logs,
        },
        shell=True,
        capture_output=True,
        check=True,
    )
    assert b"Reading head of log file" in rv.stdout


def test_log_file_not_found():
    log_dir = setup_failed_logs()
    logs_workspace = Path(__file__).parent.parent / "workspace" / "showlogs"

    rv = subprocess.run(
        f"/bin/bash show.sh -h -f error {log_dir / 'unk'}",
        cwd=logs_workspace,
        env={**environ, "PYTHONPATH": logs_workspace.parent},
        shell=True,
        capture_output=True,
        check=True,
    )
    assert b"not found" in rv.stdout
