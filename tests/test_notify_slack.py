from unittest.mock import patch

import pytest
from mocket import mocketize

from bennettbot import settings
from bennettbot.slack import notify_slack, slack_web_client
from workspace.utils.blocks import get_text_block

from .mock_http_request import get_mock_received_requests, mocket_register


@mocketize(strict_mode=True)
def test_notify_slack_success():
    mocket_register(
        {"chat.postMessage": [{"ok": True, "ts": 123.45, "channel": "test-channel"}]}
    )

    notify_slack(slack_web_client(), "test-channel", "my message", 234.56)
    latest_requests = get_mock_received_requests()["/api/chat.postMessage"]
    assert len(latest_requests) == 1
    assert latest_requests[0] == {
        "channel": "test-channel",
        "thread_ts": 234.56,
        "text": "my message",
    }


@mocketize(strict_mode=True)
def test_notify_slack_success_blocks():
    mocket_register(
        {"chat.postMessage": [{"ok": True, "ts": 123.45, "channel": "test-channel"}]}
    )
    block_message = [get_text_block(text="my message")]
    notify_slack(
        slack_web_client(),
        "test-channel",
        block_message,
        234.56,
        message_format="blocks",
    )
    latest_requests = get_mock_received_requests()["/api/chat.postMessage"]
    assert len(latest_requests) == 1
    assert latest_requests[0] == {
        "channel": "test-channel",
        "thread_ts": 234.56,
        "text": str(block_message),
        "blocks": block_message,
        "unfurl_links": False,
        "unfurl_media": False,
    }


@mocketize(strict_mode=True)
@patch("bennettbot.dispatcher.settings.MAX_SLACK_NOTIFY_RETRIES", 1)
def test_notify_slack_retries():
    # Mock 2 responses from the postMessage endpoint
    # We allow 1 retry to notify slack with the original message
    # The first attempt is an error, the second succeeds
    mocket_register(
        {"chat.postMessage": [{"ok": False, "error": "error"}, {"ok": True}]}
    )

    notify_slack(
        slack_web_client(), "test-channel", "my message", 234.56, retry_delay=0.1
    )
    latest_requests = get_mock_received_requests()["/api/chat.postMessage"]
    assert len(latest_requests) == 2
    # both attempted calls are with the original message (first errors, second succeeds)
    for request_body in latest_requests:
        assert request_body == {
            "channel": "test-channel",
            "thread_ts": 234.56,
            "text": "my message",
        }


@mocketize(strict_mode=True)
@patch("bennettbot.dispatcher.settings.MAX_SLACK_NOTIFY_RETRIES", 0)
def test_notify_slack_retries_fallback():
    # Mock 2 responses from the postMessage endpoint
    # We only allow 1 atttempt to notify slack with the original message
    # The first attempt is an error, so we fall back to notifying about the failure
    # The fallback (second mocked response) succeeds
    mocket_register(
        {"chat.postMessage": [{"ok": False, "error": "error"}, {"ok": True}]}
    )

    notify_slack(
        slack_web_client(), "test-channel", "my message", 234.56, retry_delay=0.1
    )
    latest_requests = get_mock_received_requests()["/api/chat.postMessage"]
    assert len(latest_requests) == 2

    # first attempted call with original message
    assert latest_requests[0] == {
        "channel": "test-channel",
        "thread_ts": 234.56,
        "text": "my message",
    }
    # second (successful) call with failure message
    assert latest_requests[1]["text"] == "Could not notify slack"


@mocketize(strict_mode=True)
@patch("bennettbot.dispatcher.settings.MAX_SLACK_NOTIFY_RETRIES", 1)
def test_notify_slack_retries_fallback_error():
    # Make the postMessage endpoint always error
    # We only allow 2 atttempt to notify slack with the original message
    # Both error, so we fall back to notifying about the failure
    # The fallback (second mocked response) also errors, so we give up and just log
    mocket_register({"chat.postMessage": [{"ok": False, "error": "error"}]})

    notify_slack(
        slack_web_client(), "test-channel", "my message", 234.56, retry_delay=0.1
    )
    latest_requests = get_mock_received_requests()["/api/chat.postMessage"]
    assert len(latest_requests) == 3

    for request_body in latest_requests[:2]:
        # first attempted calls with original message
        assert request_body == {
            "channel": "test-channel",
            "thread_ts": 234.56,
            "text": "my message",
        }
    # 3rd call with failure message also errors
    assert latest_requests[2]["text"] == "Could not notify slack"


@pytest.mark.parametrize(
    "token_type,token",
    [
        ("bot", settings.SLACK_BOT_TOKEN),
        ("user", settings.SLACK_BOT_USER_TOKEN),
        (None, settings.SLACK_BOT_TOKEN),
    ],
)
def test_slack_client(token_type, token):
    if token_type:
        client = slack_web_client(token_type)
    else:
        client = slack_web_client()
    assert client.token == token


def test_slack_client_with_bad_token_type():
    with pytest.raises(AssertionError, match="Unknown token type"):
        slack_web_client("unk")
