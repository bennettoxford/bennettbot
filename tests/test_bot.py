import json
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from mocket import Mocketizer, mocketize
from slack_bolt import App
from slack_bolt.request import BoltRequest
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier

from bennettbot import bot, scheduler

from .assertions import (
    assert_call_counts,
    assert_job_matches,
    assert_slack_client_doesnt_react_to_message,
    assert_slack_client_reacts_to_message,
    assert_slack_client_sends_messages,
    assert_suppression_matches,
)
from .job_configs import config
from .mock_http_request import (
    USERS,
    get_mock_received_requests,
    mocket_register,
    register_bot_uris,
)
from .time_helpers import T0, TS, T


# Make sure all tests run when datetime.now() returning T0
pytestmark = pytest.mark.freeze_time(T0)


def get_mock_app():
    app = App(raise_error_for_unhandled_request=True)
    channels = bot.get_channels(app.client)
    bot_user_id, internal_user_ids = bot.get_users_info(app.client)
    bot.join_all_channels(app.client, channels, bot_user_id)
    bot.register_listeners(app, config, channels, bot_user_id, internal_user_ids)
    return app


@pytest.fixture
def mock_app():
    register_bot_uris()
    with Mocketizer(strict_mode=True):
        mock_app = get_mock_app()
        yield mock_app


def test_joined_channels(mock_app):
    # conversations.members called for each channel (4) (to check if bot is already a
    # member) and conversations.join 3 times to join the channels it's not already in
    assert_call_counts(
        {"/api/conversations.members": 4, "/api/conversations.join": 3},
    )


@mocketize(strict_mode=True)
@pytest.mark.parametrize(
    "setting,value",
    [
        # Note: channel names are set in pyproject.toml
        # Channel ids are defined by the response from the response to
        # the conversations.list endpoint, defined in mock_http_request.py
        # support channel settings can be a channel name
        ("SLACK_TECH_SUPPORT_CHANNEL", "techsupport"),
        ("SLACK_BENNETT_ADMINS_CHANNEL", "bennettadmins"),
        # support channel settings can be a channel ID
        ("SLACK_TECH_SUPPORT_CHANNEL", "C0001"),
        ("SLACK_BENNETT_ADMINS_CHANNEL", "C0000"),
    ],
)
def test_register_listeners_support_channel_settings(setting, value):
    register_bot_uris()
    app = App(raise_error_for_unhandled_request=True)
    channels = bot.get_channels(app.client)
    bot_user_id, internal_user_ids = bot.get_users_info(app.client)
    bot.join_all_channels(app.client, channels, bot_user_id)
    with patch(f"bennettbot.settings.{setting}", value):
        bot.register_listeners(app, config, channels, bot_user_id, internal_user_ids)


@mocketize(strict_mode=True)
@pytest.mark.parametrize(
    "setting,value",
    [
        ("SLACK_TECH_SUPPORT_CHANNEL", "foo"),
        ("SLACK_BENNETT_ADMINS_CHANNEL", "C9999"),
    ],
)
def test_register_listeners_invalid_support_channel_settings(setting, value):
    register_bot_uris()
    app = App(raise_error_for_unhandled_request=True)
    channels = bot.get_channels(app.client)
    bot_user_id, internal_user_ids = bot.get_users_info(app.client)
    bot.join_all_channels(app.client, channels, bot_user_id)
    with (
        patch(f"bennettbot.settings.{setting}", value),
        pytest.raises(ValueError, match=f"channel id '{value}' not found"),
    ):
        bot.register_listeners(app, config, channels, bot_user_id, internal_user_ids)


def test_schedule_job(mock_app):
    handle_message(mock_app, "<@U1234> test do job 10")

    jj = scheduler.get_jobs_of_type("test_parameterised_job")
    assert len(jj) == 1
    assert_job_matches(
        jj[0], "test_parameterised_job", {"n": "10"}, "channel", T(60), None
    )


def test_schedule_job_with_job_already_running(mock_app):
    with patch("bennettbot.scheduler.schedule_job", return_value=True):
        handle_message(mock_app, "<@U1234> test do good job")
        assert_slack_client_sends_messages(
            messages_kwargs=[{"channel": "channel", "text": "already started"}],
        )


def test_schedule_job_from_reminder(mock_app):
    handle_message(mock_app, "Reminder: <@U1234|test bot> test do job 10")

    jj = scheduler.get_jobs_of_type("test_parameterised_job")
    assert len(jj) == 1
    assert_job_matches(
        jj[0], "test_parameterised_job", {"n": "10"}, "channel", T(60), None
    )


def test_schedule_python_job(mock_app):
    handle_message(mock_app, "<@U1234> test do python job")

    jj = scheduler.get_jobs_of_type("test_good_python_job")
    assert len(jj) == 1
    assert_job_matches(jj[0], "test_good_python_job", {}, "channel", T(0), None)


@pytest.mark.parametrize(
    "message",
    [
        "<@U1234> test do url <http://www.foo.com>",
        "<@U1234> test do url <http://www.foo.com|foo>",
        "<@U1234> test do url <http://www.foo.com|http://www.foo.com>",
    ],
)
def test_url_formatting_removed(mock_app, message):
    handle_message(mock_app, message)
    jj = scheduler.get_jobs_of_type("test_job_with_url")
    assert len(jj) == 1
    assert_job_matches(
        jj[0], "test_job_with_url", {"url": "http://www.foo.com"}, "channel", T(0), None
    )


def test_cancel_job(mock_app):
    handle_message(mock_app, "<@U1234> test do good job")
    assert scheduler.get_jobs_of_type("test_good_job")

    handle_message(mock_app, "<@U1234> test cancel job", reaction_count=2)
    assert not scheduler.get_jobs_of_type("test_good_job")


@pytest.mark.parametrize(
    "message_text",
    [
        "<@U1234> test suppress job from 11:20 to 11:30",
        "<@U1234> test suppress job from 1120 to 1130",
    ],
)
def test_schedule_suppression(mock_app, message_text):
    handle_message(mock_app, message_text)

    ss = scheduler.get_suppressions()
    assert len(ss) == 1
    assert_suppression_matches(ss[0], "test_good_job", T(467), T(1067))
    # confirmation message posted
    assert_call_counts({"/api/chat.postMessage": 1})
    assert_slack_client_sends_messages(
        messages_kwargs=[{"channel": "channel", "text": "test_good_job suppressed"}],
    )


@pytest.mark.parametrize(
    "message_text",
    [
        # bad start_at
        "<@U1234> test suppress job from 11:60 to 11:30",
        "<@U1234> test suppress job from 24:20 to 11:30",
        "<@U1234> test suppress job from xx:20 to 11:30",
        # bad end at
        "<@U1234> test suppress job from 11:20 to 11:60",
        "<@U1234> test suppress job from 11:20 to 24:30",
        "<@U1234> test suppress job from 11:20 to xx:30"
        # start at after end at
        "<@U1234> test suppress job from 11:30 to 11:20",
        # start at equal to end at
        "<@U1234> test suppress job from 11:20 to 11:20",
    ],
)
def test_schedule_suppression_with_bad_times(mock_app, message_text):
    handle_message(mock_app, message_text)
    assert_slack_client_sends_messages(
        messages_kwargs=[{"channel": "channel", "text": "`[start_at]` and `[end_at]`"}],
    )
    assert not scheduler.get_suppressions()
    # info message sent
    assert_call_counts({"/api/chat.postMessage": 1})
    assert_slack_client_sends_messages(
        messages_kwargs=[
            {
                "channel": "channel",
                "text": "Wrong time format - `[start_at]` and `[end_at]` must be HH:MM with `[start_at]` < `[end_at]`",
            }
        ],
    )


def test_cancel_suppression(mock_app):
    handle_message(mock_app, "<@U1234> test suppress job from 11:20 to 11:30")
    assert scheduler.get_suppressions()

    handle_message(mock_app, "<@U1234> test cancel suppression", reaction_count=2)
    assert not scheduler.get_suppressions()

    # confirmation messages posted
    assert_call_counts({"/api/chat.postMessage": 2})
    assert_slack_client_sends_messages(
        messages_kwargs=[
            {"channel": "channel", "text": "test_good_job suppressed"},
            {"channel": "channel", "text": "test_good_job suppressions cancelled"},
        ],
    )


def test_namespace_help(mock_app):
    handle_message(mock_app, "<@U1234> test help", reaction_count=0)
    assert_slack_client_sends_messages(
        messages_kwargs=[
            {"channel": "channel", "text": "`test do good job`: do the good job"}
        ],
    )


def test_restricted_namespace_help(mock_app):
    handle_message(mock_app, "<@U1234> testrestricted help", reaction_count=0)
    assert_slack_client_sends_messages(
        messages_kwargs=[
            {
                "channel": "channel",
                "text": ":lock: These commands are only available to Bennett Institute users",
            }
        ],
    )


def test_help(mock_app):
    handle_message(mock_app, "<@U1234> help", reaction_count=0)
    for msg_fragment in [
        "Commands in the following categories are available",
        "* `test`",
        "* `test1`: Test description",
        "* :lock: `testrestricted`",
    ]:
        assert_slack_client_sends_messages(
            messages_kwargs=[
                {"channel": "channel", "text": msg_fragment},
            ],
        )


@pytest.mark.parametrize(
    "message",
    [
        "beep boop",  # unknown command with no space after the bot mention
        " beep boop",  # unknown command
        "",  # no text, just bot mention
        ".",  # just punctuation
    ],
)
def test_not_understood(mock_app, message):
    handle_message(mock_app, f"<@U1234>{message}", reaction_count=0)
    for expected_fragment in ["I'm sorry", "Enter `@test_username [category] help`"]:
        assert_slack_client_sends_messages(
            messages_kwargs=[{"channel": "channel", "text": expected_fragment}],
        )


def test_not_understood_direct_message(mock_app):
    handle_message(
        mock_app,
        "beep boop",
        reaction_count=0,
        channel="IM0001",
        event_type="message",
        event_kwargs={"channel_type": "im"},
    )
    for expected_fragment in ["I'm sorry", "Enter `[category] help`"]:
        assert_slack_client_sends_messages(
            messages_kwargs=[{"channel": "IM0001", "text": expected_fragment}],
        )


def test_status(mock_app):
    handle_message(mock_app, "<@U1234> status", reaction_count=0)
    assert_slack_client_sends_messages(
        messages_kwargs=[{"channel": "channel", "text": "Nothing is happening"}],
    )


@pytest.mark.parametrize(
    "pre_message,message",
    [
        # handle usual spacing
        ("", " test help"),
        # no space after bot mention
        ("", "test help "),
        # additional spacing in command
        (
            "",
            "test  help",
        ),
        # additional spacing in and after ccommand
        ("", "test  help "),
        # full stop after command
        ("", " test help."),
        # text before bot mention
        ("Hey bot ", " test help"),
        # text before bot mention, no spacing
        ("Hey bot", "test help"),
    ],
)
def test_message_parsing(mock_app, pre_message, message):
    handle_message(mock_app, f"{pre_message}<@U1234>{message}", reaction_count=0)
    assert_slack_client_sends_messages(
        messages_kwargs=[
            {"channel": "channel", "text": "`test do good job`: do the good job"}
        ],
    )


def test_message_with_suffixed_text(mock_app):
    # The matcher can handle text that precedes the bot mention, but not
    # text that follows the command
    handle_message(mock_app, "<@U1234> test help me", reaction_count=0)
    for expected_fragment in ["I'm sorry", "Enter `@test_username [category] help`"]:
        assert_slack_client_sends_messages(
            messages_kwargs=[{"channel": "channel", "text": expected_fragment}],
        )


@pytest.mark.parametrize(
    "message",
    ["test help", " test  help. ", "<@U1234> test help", "hey <@U1234> test help"],
)
def test_direct_message(mock_app, message):
    # The bot can be DM'd with or without mentioning it
    # Mentions can include preceding text
    handle_message(
        mock_app,
        message,
        reaction_count=0,
        channel="IM0001",
        event_type="message",
        event_kwargs={"channel_type": "im"},
    )
    assert_slack_client_sends_messages(
        messages_kwargs=[
            {"channel": "IM0001", "text": "`test do good job`: do the good job"}
        ],
    )


@pytest.mark.parametrize("message", ["test help me", "hey test help"])
def test_direct_message_without_bot_mention_must_contain_command_only(
    mock_app, message
):
    # DMs can handle extra whitespace and following full stop as usual, but
    # can't handle text preceding or following the command
    handle_message(
        mock_app,
        message,
        reaction_count=0,
        channel="IM0001",
        event_type="message",
        event_kwargs={"channel_type": "im"},
    )
    for expected_fragment in ["I'm sorry", "Enter `[category] help`"]:
        assert_slack_client_sends_messages(
            messages_kwargs=[{"channel": "IM0001", "text": expected_fragment}],
        )


def test_build_status():
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    scheduler.schedule_job("odd_job", {"k": "v"}, "channel", TS, 10)
    scheduler.schedule_suppression("odd_job", T(-5), T(5))
    scheduler.schedule_suppression("good_job", T(5), T(15))
    scheduler.reserve_job()

    status = bot._build_status()

    assert (
        status
        == """
The time is 2019-12-10 11:12:13+00:00

There is 1 running job:

* [1] good_job (started at 2019-12-10 11:12:13+00:00)

There is 1 scheduled job:

* [2] odd_job (starting after 2019-12-10 11:12:23+00:00)

There is 1 active suppression:

* [1] odd_job (from 2019-12-10 11:12:08+00:00 to 2019-12-10 11:12:18+00:00)

There is 1 scheduled suppression:

* [2] good_job (from 2019-12-10 11:12:18+00:00 to 2019-12-10 11:12:28+00:00)
""".strip()
    )


def test_pluralise():
    assert bot._pluralise(0, "bot") == "There are 0 bots"
    assert bot._pluralise(1, "bot") == "There is 1 bot"
    assert bot._pluralise(2, "bot") == "There are 2 bots"


def _tech_support_test_params():
    return [
        # We only match the hyphenated keywords "tech-support"
        ("This message should not match the tech support listener", "C0002", {}, None),
        # We match only distinct words
        (
            "This message should not match the test-tech-support listener",
            "C0002",
            {},
            None,
        ),
        (
            "This message should not match the tech-support-test listener",
            "C0002",
            {},
            None,
        ),
        # We ignore mentions embeded in URLs
        (
            "This message should not match the /test/tech-support listener",
            "C0002",
            {},
            None,
        ),
        # a message posted in the techsupport channel (C0001) does not repost
        ("This message should not match the tech-support listener", "C0001", {}, None),
        # a message posted by a bot with the right keywords and channel does not repost
        (
            "This message should not match the tech-support listener",
            "C0002",
            {"bot_id": "B1"},
            None,
        ),
        ("This message should match the tech-support listener", "C0003", {}, "C0001"),
        ("This message should match the Tech-support listener", "C0002", {}, "C0001"),
        ("This message should match the tech-SUPPORT listener", "C0002", {}, "C0001"),
        ("This message should match the @tech-support listener", "C0002", {}, "C0001"),
        ("This message should match the #tech-support listener", "C0002", {}, "C0001"),
        ("This message should match the `tech-support` listener", "C0002", {}, "C0001"),
        ("tech-support - this message should match", "C0002", {}, "C0001"),
        ("This message should match - tech-support", "C0002", {}, "C0001"),
        ("This message should match the bennett-admins listener", "C0002", {}, "C0000"),
        # deliberate typo below
        ("This message should match the bennet-admins listener", "C0002", {}, "C0000"),
    ]


@pytest.mark.parametrize(
    "text,channel,event_kwargs,repost_channel",
    _tech_support_test_params(),
)
def test_tech_support_listener(mock_app, text, channel, event_kwargs, repost_channel):
    # test that we get the expected response with an initial tech-support message
    assert_expected_support_response(
        mock_app, text, channel, event_kwargs, repost_channel
    )


@pytest.mark.parametrize(
    "text,channel,event_kwargs,repost_expected",
    _tech_support_test_params(),
)
def test_tech_support_listener_for_changed_messages(
    mock_app, text, channel, event_kwargs, repost_expected
):
    # test that we also get the expected response for a changed message
    event_kwargs.update({"subtype": "message_changed"})
    assert_expected_support_response(
        mock_app, text, channel, event_kwargs, repost_expected
    )


def test_tech_support_listener_ignores_non_message_changed_subtypes(mock_app):
    assert_expected_support_response(
        mock_app,
        text="A tech-support message that would usually match",
        channel="C0002",
        event_kwargs={"subtype": "reminder_add"},
        repost_channel=None,
    )


def assert_tech_support_paths_not_called():
    received_requests = get_mock_received_requests()
    for path in ["/api/chat.getPermalink", "/api/chat.postMessage"]:
        assert path not in received_requests


def assert_tech_support_paths_called():
    received_requests = get_mock_received_requests()
    for path in ["/api/chat.getPermalink", "/api/chat.postMessage"]:
        assert len(received_requests[path]) == 1


def assert_expected_support_response(
    mock_app, text, channel, event_kwargs, repost_channel
):
    # the triggered tech support handler will first fetch the url for the message
    # and then post it to the techsupport channel
    # Before the dispatched message, neither of these paths have been called
    assert_tech_support_paths_not_called()

    handle_message(
        mock_app,
        text,
        channel=channel,
        reaction_count=1 if repost_channel else 0,
        event_type="message",
        event_kwargs=event_kwargs,
    )

    # After the dispatched message, each path has been called once
    if repost_channel:
        assert_tech_support_paths_called()
    else:
        assert_tech_support_paths_not_called()

    if repost_channel:
        received_requests = get_mock_received_requests()
        # check the contents of the request kwargs for the postMessage
        # posts to the repost channel, with the url retrieved from the
        # mocked getPermalink call (always "http://example.com")
        post_message = received_requests["/api/chat.postMessage"][0]
        assert ("text", "http://example.com") in post_message.items()
        assert ("channel", repost_channel) in post_message.items()


def test_tech_support_edited_message(mock_app):
    # the triggered tech support handler will first fetch the url for the message
    # and then post it to the techsupport channel
    # Before the dispatched message, neither of these paths have been called
    assert_tech_support_paths_not_called()

    handle_message(
        mock_app,
        "get tec-support",
        channel="C0002",
        reaction_count=0,
        event_type="message",
        event_kwargs={"subtype": "message_changed"},
    )

    # tech-support keyword typo, no tech support calls
    assert_tech_support_paths_not_called()

    # Editing the same message to include tech-support does repost
    handle_message(
        mock_app,
        "get tech-support",
        channel="C0002",
        reaction_count=1,
        event_type="message",
        event_kwargs={"subtype": "message_changed"},
    )

    assert_tech_support_paths_called()


@patch("bennettbot.bot.get_tech_support_dates")
def test_tech_support_out_of_office_listener(tech_support_dates, mock_app):
    start = (datetime.today() - timedelta(1)).date()
    end = (datetime.today() + timedelta(1)).date()
    tech_support_dates.return_value = start, end

    # If tech-support is OOO, the handler will first reply with the OOO message, then
    # the repost the message URL to the techsupport channel
    # Before the dispatched message, neither of these paths have been called
    assert_tech_support_paths_not_called()

    handle_message(
        mock_app,
        "Calling tech-support",
        channel="C0002",
        reaction_count=1,
        event_type="message",
        event_kwargs={},
    )

    # After the dispatched message, postMessage has been called twice, for the OOO
    # reply and the reposted url
    received_requests = get_mock_received_requests()
    assert len(received_requests["/api/chat.postMessage"]) == 2
    assert len(received_requests["/api/chat.getPermalink"]) == 1

    # check the contents of the request kwargs for the OOO postMessage
    # posts to the same channel (C0002)
    ooo_message = received_requests["/api/chat.postMessage"][0]
    assert "tech-support is currently out of office" in ooo_message["text"]
    assert ooo_message["channel"] == "C0002"
    # check the contents of the request kwargs for the reposted postMessage
    # posts to the techsupport channel (C0001), with the url retrieved from the
    # mocked getPermalink call (always "http://example.com")
    repost_message = received_requests["/api/chat.postMessage"][1]
    assert repost_message["text"] == "http://example.com"
    assert repost_message["channel"] == "C0001"


@pytest.mark.parametrize(
    "start_days_from_today,end_days_from_today,ooo_message",
    [
        (-10, -5, False),  # both past
        (5, 10, False),  # both future
        (-2, 10, True),  # ooo currently on
    ],
)
@patch("bennettbot.bot.get_tech_support_dates")
def test_tech_support_out_of_office_dates(
    tech_support_dates,
    mock_app,
    start_days_from_today,
    end_days_from_today,
    ooo_message,
):
    start = (datetime.today() + timedelta(start_days_from_today)).date()
    end = (datetime.today() + timedelta(end_days_from_today)).date()
    tech_support_dates.return_value = start, end

    # If tech-support is OOO, the handler will first reply with the OOO message, then
    # the repost the message URL to the techsupport channel
    # Before the dispatched message, neither of these paths have been called
    assert_tech_support_paths_not_called()

    handle_message(
        mock_app,
        "Calling tech-support",
        channel="C0002",
        reaction_count=1,
        event_type="message",
        event_kwargs={},
    )

    # After the dispatched message, postMessage has been called twice if OOO, for the OOO
    # reply and the reposted url
    received_requests = get_mock_received_requests()
    assert len(received_requests["/api/chat.postMessage"]) == 2 if ooo_message else 1
    assert len(received_requests["/api/chat.getPermalink"]) == 1

    first_message = received_requests["/api/chat.postMessage"][0]
    if ooo_message:
        assert "tech-support is currently out of office" in first_message["text"]
    else:
        assert first_message["text"] == "http://example.com"


def test_tech_support_listener_in_direct_message(mock_app):
    # If the tech support handler is triggered in a DM, it doesn't get
    # reposted to the techsupport channel
    assert_tech_support_paths_not_called()

    handle_message(
        mock_app,
        "Calling tech-support",
        channel="IM0001",
        reaction_count=0,
        event_type="message",
        event_kwargs={"channel_type": "im"},
    )
    received_requests = get_mock_received_requests()
    assert "/api/chat.getPermalink" not in received_requests
    assert "/api/chat.postMessage" in received_requests
    post_message = received_requests["/api/chat.postMessage"][0]
    assert (
        "text",
        "Sorry, I can't call tech-support from this conversation.",
    ) in post_message.items()
    assert ("channel", "IM0001") in post_message.items()


def test_no_listener_found(mock_app):
    # A message must either start with "<@U1234>" (i.e. a user @'d the bot) OR must contain
    # the tech-support pattern
    text = "This message should not match any listener"
    # We use an error handler to deal with unhandled messages, so the response status
    # is 200
    resp = handle_message(
        mock_app,
        text,
        channel="C0002",
        reaction_count=0,
        expected_status=200,
        event_type="message",
    )
    assert_slack_client_sends_messages(messages_kwargs=[])
    assert resp.body == "Unhandled message"


def test_unexpected_error(mock_app):
    # Unexpected errors post a X reaction and respond with the error
    with patch("bennettbot.bot.handle_namespace_help", side_effect=Exception):
        handle_message(
            mock_app,
            "<@U1234> test help",
            reaction_count=1,
            expected_status=500,
        )
    assert_slack_client_sends_messages(
        messages_kwargs=[
            {
                "channel": "channel",
                "text": "Unexpected error: Exception()\nwhile responding to message `test help`",
            }
        ],
    )


def test_already_reacted_to_tech_support_error(mock_app):
    # mock an error from a method that's called during the tech-support
    # handling to return an "already reacted" SlackApiError
    with patch(
        "bennettbot.bot.tech_support_out_of_office",
        side_effect=SlackApiError(
            message="Error", response=Mock(data={"error": "already_reacted"})
        ),
    ):
        handle_message(
            mock_app,
            "tech-support help",
            channel="channel",
            reaction_count=1,
            event_type="message",
            expected_status=200,
        )

    assert_slack_client_sends_messages(messages_kwargs=[])


def test_already_reacted_to_non_tech_support_error(mock_app):
    # Only already-reacted to tech support messages are ignored;
    # another sort of message that raises this error gets
    # reported back to slack
    with patch(
        "bennettbot.bot.handle_namespace_help",
        side_effect=SlackApiError(
            message="Error", response=Mock(data={"error": "already_reacted"})
        ),
    ):
        handle_message(
            mock_app,
            "<@U1234> test help",
            reaction_count=1,
            expected_status=500,
        )

    assert_slack_client_sends_messages(
        messages_kwargs=[
            {
                "channel": "channel",
                "text": "Unexpected error: SlackApiError",
            }
        ],
    )


def test_new_channel_created(mock_app):
    # When a channel_created event is received, the bot user joins that channel
    handle_event(
        mock_app,
        event_type="channel_created",
        event_kwargs={"channel": {"id": "C0NEW", "name": "new-channel"}},
    )
    assert_slack_client_sends_messages(messages_kwargs=[])
    received_requests = get_mock_received_requests()
    assert received_requests["/api/conversations.join"][-1] == {
        "channel": ["C0NEW"],
        "users": ["U1234"],
    }


def test_remove_job(mock_app):
    handle_message(mock_app, "<@U1234> test do good job", reaction_count=1)
    jobs = scheduler.get_jobs_of_type("test_good_job")
    assert len(jobs) == 1
    job_id = jobs[0]["id"]
    handle_message(mock_app, f"<@U1234> remove job id {job_id}", reaction_count=2)
    assert not scheduler.get_jobs_of_type("test_good_job")

    received_requests = get_mock_received_requests()
    post_message = received_requests["/api/chat.postMessage"][0]
    assert (
        "text",
        "Job id [1] removed",
    ) in post_message.items()


def test_remove_non_existent_job(mock_app):
    handle_message(mock_app, "<@U1234> remove job id 10", reaction_count=1)
    received_requests = get_mock_received_requests()
    post_message = received_requests["/api/chat.postMessage"][0]
    assert (
        "text",
        "Job id [10] not found in running or scheduled jobs",
    ) in post_message.items()


@pytest.mark.parametrize(
    "user,command,reaction_count,scheduled_job_count",
    [
        # guest user, unrestricted job
        ("UGUEST", "test do job 1", 1, 1),
        # internal user, restricted job
        ("UINT", "testrestricted do job", 1, 1),
        # guest user, restricted job
        ("UGUEST", "testrestricted do job", 0, 0),
        # new internal user, restricted job
        ("NEWINT", "testrestricted do job", 1, 1),
        # new guest user, restricted job
        ("NEWGUEST", "testrestricted do job", 0, 0),
    ],
)
def test_restricted_jobs_only_scheduled_for_internal_users(
    mock_app, user, command, reaction_count, scheduled_job_count
):
    mocket_register({"users.info": [{"ok": True, "user": USERS[user]}]})

    assert not scheduler.get_jobs()
    handle_message(
        mock_app,
        f"<@U1234> {command}",
        event_kwargs={"user": user},
        reaction_count=reaction_count,
    )
    assert len(scheduler.get_jobs()) == scheduled_job_count
    if scheduled_job_count == 0:
        assert_slack_client_sends_messages(
            messages_kwargs=[{"channel": "channel", "text": ":no_entry:"}],
        )


def handle_message(
    mock_app,
    text,
    *,
    reaction_count=1,
    channel="channel",
    event_type="app_mention",
    event_kwargs=None,
    expected_status=200,
):
    event_kwargs = event_kwargs or {}
    event_kwargs.update({"channel": channel})
    # If it's a message_changed message event, has a "message"
    # key with a dict containing the current message text and ts
    # (and other elements that we don't use)
    # Non-changed messages and other events,such as "app_mention",
    # won't contain "message"
    if event_kwargs.get("subtype") == "message_changed":
        event_kwargs.update({"message": {"text": text, "ts": "1596183880.004200"}})
    else:
        event_kwargs.update({"text": text})

    resp = handle_event(
        mock_app,
        event_type=event_type,
        event_kwargs=event_kwargs,
        expected_status=expected_status,
    )

    if reaction_count:
        assert_slack_client_reacts_to_message(reaction_count)
    else:
        assert_slack_client_doesnt_react_to_message()

    return resp


def handle_event(mock_app, event_type, event_kwargs, expected_status=200):
    request = get_mock_request(event_type, event_kwargs)
    resp = mock_app.dispatch(request)
    # App.dispatch() applies all middleware and dispatches the request to the correct
    # code path.
    # https://github.com/slackapi/bolt-python/blob/v1.6.1/slack_bolt/app/app.py#L433
    # Initially the response has status 200 and body "" (the default in the dispatch method).
    # This is the response that the dispatch method returns as it applies middleware
    # Previously this function just waited for 0.1 seconds to allow the resp to settle,
    # but occasionally in CI that appears to not be long enough. We now give it 5 attempts
    # to resolve
    # Note: we check for a resp.body because all tests that use this method return _something_ in
    # their body, whether they're expected to be successful or not.
    attempts = 0
    while resp.body == "" and attempts < 5:
        attempts += 1
        time.sleep(0.1)

    assert resp.status == expected_status
    return resp


def get_mock_request(event_type, event_kwargs):
    body = {
        "token": "verification_token",
        "team_id": "T111",
        "enterprise_id": "E111",
        "api_app_id": "A111",
        "event": {
            "client_msg_id": "a8744611-0210-4f85-9f15-5faf7fb225c8",
            "type": event_type,
            "user": "W111",
            "ts": "1596183880.004200",
            "team": "T111",
            "event_ts": "1596183880.004200",
            "channel_type": "channel",
        },
        "type": "event_callback",
        "event_id": "Ev111",
        "event_time": 1596183880,
    }
    body["event"].update(event_kwargs)
    timestamp, body = str(int(time.time())), json.dumps(body)
    signature = SignatureVerifier("secret").generate_signature(
        body=body,
        timestamp=timestamp,
    )
    headers = {
        "content-type": ["application/json"],
        "x-slack-signature": [signature],
        "x-slack-request-timestamp": [timestamp],
    }
    return BoltRequest(body=body, headers=headers)
