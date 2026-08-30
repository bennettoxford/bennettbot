import hashlib
import hmac
from unittest.mock import patch

import pytest
from mocket import Mocket, mocketize

from bennettbot import scheduler, settings
from bennettbot.job_configs import build_config

from ..assertions import assert_job_matches, assert_slack_client_sends_messages
from ..mock_http_request import mocket_register
from ..time_helpers import T0, T


# Make sure all tests run when datetime.now() returning T0
pytestmark = pytest.mark.freeze_time(T0)


PAYLOAD_PR_CLOSED = '{"action": "closed", "pull_request": {"merged": true}}'
PAYLOAD_PR_CLOSED_UNMERGED = '{"action": "closed", "pull_request": {"merged": false}}'
PAYLOAD_PR_OPENED = '{"action": "opened", "pull_request": {}}'
PAYLOAD_ISSUE_OPENED = '{"action": "opened", "issue": {}}'
PAYLOAD_WORKFLOW_RUN_COMPLETED = '{"action": "completed", "workflow_run": {"name": "CI", "status": "completed", "conclusion": "success", "head_branch": "main"}, "repository": {"full_name": "owner/repo"}}'
PAYLOAD_WORKFLOW_RUN_IN_PROGRESS = '{"action": "in_progress", "workflow_run": {"name": "CI", "status": "in_progress", "head_branch": "main"}, "repository": {"full_name": "owner/repo"}}'


dummy_config = build_config(
    {
        "test": {
            "default_channel": "#some-team",
            "jobs": {"deploy": {"run_args_template": "fab deploy:production"}},
            "slack": [],
        }
    }
)


def test_no_auth_header(web_client):
    rsp = web_client.post("/github/test/", data=PAYLOAD_PR_CLOSED)
    assert rsp.status_code == 403


def test_malformed_auth_header(web_client):
    headers = {"X-Hub-Signature": "abcdef"}
    rsp = web_client.post("/github/test/", data=PAYLOAD_PR_CLOSED, headers=headers)
    assert rsp.status_code == 403


def test_invalid_auth_header(web_client):
    headers = {"X-Hub-Signature": "sha1=abcdef"}
    rsp = web_client.post("/github/test/", data=PAYLOAD_PR_CLOSED, headers=headers)
    assert rsp.status_code == 403


def test_valid_auth_header(web_client):
    headers = {"X-Hub-Signature": compute_signature(PAYLOAD_PR_CLOSED)}

    with patch("bennettbot.webserver.github.config", new=dummy_config):
        rsp = web_client.post("/github/test/", data=PAYLOAD_PR_CLOSED, headers=headers)

    assert rsp.status_code == 200


@mocketize(strict_mode=True)
def test_on_closed_merged_pr(web_client):
    mocket_register({"chat.postMessage": {"ok": True}})
    headers = {"X-Hub-Signature": compute_signature(PAYLOAD_PR_CLOSED)}

    with patch("bennettbot.webserver.github.config", new=dummy_config):
        rsp = web_client.post("/github/test/", data=PAYLOAD_PR_CLOSED, headers=headers)

    assert rsp.status_code == 200
    jj = scheduler.get_jobs_of_type("test_deploy")
    assert len(jj) == 1
    assert_job_matches(jj[0], "test_deploy", {}, "#some-team", T(60), None)
    # no suppressions, no messages sent
    assert_slack_client_sends_messages(messages_kwargs=[])


@mocketize(strict_mode=True)
def test_on_closed_merged_pr_with_suppression(web_client):
    mocket_register({"chat.postMessage": [{"ok": True}]})
    scheduler.schedule_suppression("test_deploy", T(-60), T(60))

    headers = {
        "X-Hub-Signature": compute_signature(PAYLOAD_PR_CLOSED),
    }

    with patch("bennettbot.webserver.github.config", new=dummy_config):
        rsp = web_client.post("/github/test/", data=PAYLOAD_PR_CLOSED, headers=headers)

    assert rsp.status_code == 200
    jj = scheduler.get_jobs_of_type("test_deploy")
    assert len(jj) == 1
    assert_job_matches(jj[0], "test_deploy", {}, "#some-team", T(60), None)

    # message sent for suppression
    assert len(Mocket.request_list()) == 1
    assert_slack_client_sends_messages(
        messages_kwargs=[{"text": f"suppressed until {T(60)}", "channel": "#some-team"}]
    )


def test_on_closed_unmerged_pr(web_client):
    headers = {"X-Hub-Signature": compute_signature(PAYLOAD_PR_CLOSED_UNMERGED)}
    rsp = web_client.post(
        "/github/test/", data=PAYLOAD_PR_CLOSED_UNMERGED, headers=headers
    )
    assert rsp.status_code == 200
    assert not scheduler.get_jobs_of_type("test_deploy")


def test_on_opened_pr(web_client):
    headers = {"X-Hub-Signature": compute_signature(PAYLOAD_PR_OPENED)}
    rsp = web_client.post("/github/test/", data=PAYLOAD_PR_OPENED, headers=headers)
    assert rsp.status_code == 200
    assert not scheduler.get_jobs_of_type("test_deploy")


def test_on_opened_issue(web_client):
    headers = {"X-Hub-Signature": compute_signature(PAYLOAD_ISSUE_OPENED)}
    rsp = web_client.post("/github/test/", data=PAYLOAD_ISSUE_OPENED, headers=headers)
    assert rsp.status_code == 200
    assert not scheduler.get_jobs_of_type("test_deploy")


def test_unknown_project(web_client):
    headers = {"X-Hub-Signature": compute_signature(PAYLOAD_PR_CLOSED)}
    rsp = web_client.post(
        "/github/another-name/", data=PAYLOAD_PR_CLOSED, headers=headers
    )
    assert rsp.status_code == 400
    assert rsp.data == b"Unknown project: another-name"


@mocketize(strict_mode=True)
def test_workflow_run_completed(web_client):
    mocket_register({"chat.postMessage": [{"ok": True}]})
    headers = {"X-Hub-Signature": compute_signature(PAYLOAD_WORKFLOW_RUN_COMPLETED)}

    with patch("bennettbot.webserver.github.config", new=dummy_config):
        rsp = web_client.post(
            "/github/test/", data=PAYLOAD_WORKFLOW_RUN_COMPLETED, headers=headers
        )

    assert rsp.status_code == 200
    assert_slack_client_sends_messages(
        messages_kwargs=[
            {
                "text": "✅ Workflow 'CI' success in owner/repo on main",
                "channel": "#some-team",
            }
        ]
    )


def test_workflow_run_in_progress(web_client):
    headers = {"X-Hub-Signature": compute_signature(PAYLOAD_WORKFLOW_RUN_IN_PROGRESS)}
    rsp = web_client.post(
        "/github/test/", data=PAYLOAD_WORKFLOW_RUN_IN_PROGRESS, headers=headers
    )
    assert rsp.status_code == 200


def compute_signature(payload):
    """Compute HMAC-SHA1 signature for a payload using the test webhook secret."""
    signature = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET, payload.encode(), hashlib.sha1
    ).hexdigest()
    return f"sha1={signature}"
