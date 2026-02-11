import random
import re
from datetime import UTC, datetime
from threading import Event

from slack_bolt import App, BoltResponse
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt.error import BoltUnhandledRequestError
from slack_bolt.util.utils import get_boot_message
from slack_sdk.errors import SlackApiError

from workspace.techsupport.jobs import get_dates_from_config as get_tech_support_dates

from . import job_configs, scheduler, settings
from .config import get_support_config
from .logger import log_call, logger
from .slack import notify_slack


class SocketModeCheckHandler(SocketModeHandler):
    def start(self):  # pragma: no cover
        """
        Duplicates the behaviour of SocketModeHandler (establishes a new connection and then blocks the current thread to prevent the termination of this process).

        In addition, sets a file after connection that can used as a healthcheck to
        ensure that the bot is fully running. In production, this file is removed in a dokku release task that runs pre-deploy.
        """
        settings.BOT_CHECK_FILE.unlink(missing_ok=True)

        self.connect()
        logger.info(get_boot_message())

        settings.BOT_CHECK_FILE.touch()
        Event().wait()


def run():  # pragma: no cover
    """Start the bot running."""
    app = App(
        token=settings.SLACK_BOT_TOKEN,
        signing_secret=settings.SLACK_SIGNING_SECRET,
        # enable @app.error handler to catch the patterns we don't specifically handle
        raise_error_for_unhandled_request=True,
    )
    handler = SocketModeCheckHandler(app, settings.SLACK_APP_TOKEN)

    bot_user_id, internal_user_ids = get_users_info(app.client)
    channels = get_channels(app.client)
    join_all_channels(app.client, channels, bot_user_id)
    register_listeners(
        app, job_configs.config, channels, bot_user_id, internal_user_ids
    )
    handler.start()
    logger.info("Connected")


def get_users_info(client):
    users = {user["name"]: user for user in client.users_list()["members"]}
    internal_user_ids = {
        user["id"]
        for user in users.values()
        if not user["is_bot"] and not user.get("is_restricted", True)
    }
    return users[settings.SLACK_APP_USERNAME]["id"], internal_user_ids


def user_is_guest(client, user_id):
    user = client.users_info(user=user_id)["user"]
    return user.get("is_restricted", True)


def get_channels(client):
    return {
        channel["name"]: channel["id"]
        for channel in client.conversations_list(types="public_channel", limit=1000)[
            "channels"
        ]
        if not channel["is_archived"]
    }


def join_all_channels(client, channels, user_id):
    joined = []
    for channel_name, channel_id in channels.items():
        if user_id not in client.conversations_members(channel=channel_id)["members"]:
            logger.info("Bot user joining channel", channel=channel_name)
            client.conversations_join(channel=channel_id, users=user_id)
            joined.append(channel_name)
    return joined


def tech_support_out_of_office():
    start, end = get_tech_support_dates()
    today = datetime.today().date()
    if start and end and (start <= today <= end):
        return end


def register_listeners(app, config, channels, bot_user_id, internal_user_ids):
    """
    Register listeners for this app

    - A single listener for slack requests that mention the bot
    - A single listener for slack requests in DMs with the bot
    - A tech-support listener
    - An error handler
    - A listener for new channels

    The listeners are defined inside this function to allow different config to be
    passed in for tests.
    """
    support_config = get_support_config(channels)
    # Check that channel settings mapped to valid channel IDs
    for support in support_config.values():
        if support["support_channel"] not in channels.values():
            raise ValueError(
                f"{support['keyword']} channel id '{support['support_channel']}' not found"
            )

    @app.event(
        "app_mention",
        # Don't match app mentions that include tech support keywords; these will be
        # matched by the tech-support listener
        matchers=[
            lambda event: (
                not support_config["tech-support"]["regex"].match(event["text"])
            )
        ],
    )
    def job_listener(event, say, ack):
        """Respond to every Slack message that mentions the bot (and is not a
        tech-support message) and dispatch to another handler based on the contents
        of the message.

        This allows us to define handlers dynamically based on the job config.
        """
        logger.info(event=event)
        # acknowledge this message to avoid slack retrying in 3s
        ack()
        _listener(event, say)

    @app.message(
        ".*",
        # only match DMs with the bot that are non-tech support messages
        matchers=[
            lambda message: (
                message["channel_type"] == "im"
                and not support_config["tech-support"]["regex"].match(message["text"])
            )
        ],
    )
    def im_job_listener(event, say, ack):
        """Respond to every Slack message in a direct message with the bot and dispatch
        to another handler based on the contents of the message.
        """
        # acknowledge this message to avoid slack retrying in 3s
        ack()
        _listener(event, say, is_im=True)

    def _listener(event, say, is_im=False):
        # Find the text that follows the bot mention, which can be in the form of
        # <@AB1234|bot_name> or <@AB1234>
        # We don't require the bot mention to be first in the message.
        # We allow for users ending the command with a ., but we don't allow
        # any additional text to follow the command.
        # (we probably could do this, but the various regexes for commands take many
        # formats, and it could be error prone to try partially matching them. Some are
        # subsets of others, for example.)
        # We allow for random whitespace in/before/after the command
        # We also allow commands on their own with no bot mention (matched in DMs with the bot)

        # we should match any of there
        # - "Reminder: <@bot|bot_name> do the thing"
        # - "<@bot> do the thing"
        # - "<@bot>do the thing"
        # - "<@bot>  do the thing "
        # - "<@bot> do the thing."
        # - "hello, <@bot> do the thing"
        # - "do the thing"
        # - " do the  thing "
        # But not:
        # - "<@bot> do the thing please"
        text = event["text"]
        if bot_user_id in text:
            # extract the command text from a bot mention
            # If the bot isn't mentioned, it's a DM and we expect to receive
            # a message with just a command (but allowing for spurious whitespace
            # and punctuation, which we'll deal with later
            text_match = re.match(
                (
                    rf".*"  # allow anything before the bot mention
                    rf"(<@{bot_user_id}(|.+)?>)"  # match either <@bot_id> or <"bot_id|bot_name">
                    rf"(?P<text_match>.*)"  # capture everything else (including nothing) in a named group
                ),
                text,
                flags=re.X,  # ignore whitespace in the regex
            )
            text = text_match.group("text_match")

        # handle extra whitespace and punctuation
        text = " ".join(text.strip().rstrip(".").split())
        event["text"] = text
        logger.info("Received message", message=text)

        if text == "status":
            handle_status(event, say)
            return

        if text.startswith("remove job id"):
            handle_remove_job(app, event, say, text)
            return

        for slack_config in config["slack"]:
            if slack_config["regex"].match(text):
                if not user_has_permission(
                    app, event, say, text, config["restricted"], internal_user_ids
                ):
                    return
                handle_command(app, event, say, slack_config, is_im=is_im)
                return

        for namespace, help_config in config["help"].items():
            for pattern in [f"^{namespace} help$", f"^help {namespace}$"]:
                if re.match(pattern, text):
                    handle_namespace_help(
                        event, say, help_config, config["restricted"][namespace]
                    )
                    return

        include_apology = text != "help"
        handle_help(event, say, config, include_apology)

    def build_matcher(*, regex, support_channel, **kwargs):
        """Builds matcher to match messages matching given regex but not posted in given channel."""

        def matcher(event):
            # Only match messages posted outside of the channel itself
            if event["channel"] == support_channel:
                return False
            # only match messages that are not posted by a bot, to avoid reposting reminders etc
            # (the event dict will include the key "bot_id")
            if "bot_id" in event:
                return False
            # Of the available message subtypes, only match "message_changed"; we don't
            # want to match e.g. "reminder_add" messages that include the word "tech-support"
            subtype = event.get("subtype")
            if subtype and subtype != "message_changed":
                return False

            # match the keyword
            text = event.get("message", event)["text"]
            return regex.match(text) is not None

        return matcher

    @app.event(
        {"type": "message"},
        matchers=[build_matcher(**support_config["bennett-admins"])],
    )
    def repost_to_bennett_admins(event, say, ack):
        repost_support_request_to_channel(
            event, say, ack, **support_config["bennett-admins"]
        )

    @app.event(
        {"type": "message"},
        matchers=[build_matcher(**support_config["tech-support"])],
    )
    def repost_to_tech_support(event, say, ack):
        repost_support_request_to_channel(
            event, say, ack, **support_config["tech-support"]
        )

    def repost_support_request_to_channel(
        event, say, ack, *, keyword, reaction, support_channel, **kwargs
    ):
        # acknowledge the messages
        ack()
        # Our matcher filters only allows messages with no subtype (i.e. just
        # straightforward posts) or message_changed subtype
        # For edited messages (message_changed), the text is found in the event's
        # "message"; for other messages, the event itself contains the text
        message = event.get("message", event)
        channel = event["channel"]
        # Don't repost messages in DMs with the bot
        # We don't use the matcher for this, because we want to tell users to
        # call for support from a non-dm channel
        if event["channel_type"] in ["channel", "group"]:
            # Respond with reaction
            # If we've already responded, the attempt to react here will raise
            # an exception; if this happens, then the user is editing something
            # other than the keyword in the message, and we don't need to repost
            # it again. We let the default error handler will deal with it.
            app.client.reactions_add(
                channel=channel, timestamp=message["ts"], name=reaction
            )
            logger.info(f"Received {keyword} message", message=message["text"])
            if keyword == "tech-support":
                # If out of office, respond with an ooo message, but still repost to channel
                out_of_office_until = tech_support_out_of_office()
                if out_of_office_until:
                    logger.info("Tech support OOO", until=out_of_office_until)
                    say(
                        f"tech-support is currently out of office and will respond after {out_of_office_until}",
                        channel=channel,
                        thread_ts=message["ts"],
                    )

            message_url = app.client.chat_getPermalink(
                channel=channel, message_ts=message["ts"]
            )["permalink"]
            say(message_url, channel=support_channel)
        else:
            say(
                f"Sorry, I can't call {keyword} from this conversation.",
                channel=channel,
            )

    @app.event("channel_created")
    def join_channel(event, ack):
        channel = event["channel"]
        logger.info("Received new channel event", channel=channel["id"])
        ack()
        logger.info("Bot user joining channel", name=channel["name"], id=channel["id"])
        app.client.conversations_join(channel=channel["id"], users=bot_user_id)

    @app.error
    def handle_errors(error, body):
        if "message" in body["event"]:
            message_text = body["event"]["message"]["text"]
        else:
            message_text = body["event"].get("text", "")

        if isinstance(error, BoltUnhandledRequestError):
            # Unhandled messages are common (anything that doesn't get matched
            # by one of the listeners).  We don't want to log those.
            return BoltResponse(status=200, body="Unhandled message")
        elif (
            isinstance(error, SlackApiError)
            and error.response.data["error"] == "already_reacted"
            and "tech-support" in message_text
        ):
            # If we're already reacted to a tech-support message and the
            # user edits the message, we get a slack error, but that's OK
            logger.info(
                "Already reacted to tech-support message",
                message=message_text,
            )
            return BoltResponse(
                status=200, body="Already reacted to tech-support message"
            )
        else:
            # other error patterns
            channel = body["event"]["channel"]
            ts = body["event"]["ts"]
            logger.error("Unexpected error", error=error, body=body)
            app.client.reactions_add(channel=channel, timestamp=ts, name="x")
            notify_slack(
                app.client,
                channel,
                f"Unexpected error: {repr(error)}\nwhile responding to message `{message_text}`",
                thread_ts=ts,
            )
            return BoltResponse(status=500, body="Something went wrong")


@log_call
def handle_status(message, say):
    """Report status of jobs and suppressions back to Slack."""

    status = _build_status()
    say(status, thread_ts=message.get("thread_ts"))


@log_call
def handle_remove_job(app, message, say, text):
    """Remove a job from the database so it can be rerun."""
    app.client.reactions_add(
        channel=message["channel"], timestamp=message["ts"], name="crossed_fingers"
    )
    job_id = int(text.split("remove job id ")[1])
    jobs_ids = [job["id"] for job in scheduler.get_jobs()]
    if job_id not in jobs_ids:
        say(
            f"Job id [{job_id}] not found in running or scheduled jobs",
            thread_ts=message.get("thread_ts"),
        )
    else:
        scheduler.mark_job_done(job_id)
        say(f"Job id [{job_id}] removed", thread_ts=message.get("thread_ts"))


def _build_status():
    running_jobs = []
    scheduled_jobs = []

    for j in scheduler.get_jobs():
        if j["started_at"]:
            running_jobs.append(j)
        else:
            scheduled_jobs.append(j)

    active_suppressions = []
    scheduled_suppressions = []

    for suppression in scheduler.get_suppressions():
        if suppression["start_at"] < str(_now()):
            active_suppressions.append(suppression)
        else:
            scheduled_suppressions.append(suppression)
    lines = [f"The time is {_now()}", ""]

    if running_jobs:
        lines.append(_pluralise(len(running_jobs), "running job:"))
        lines.append("")
        for j in running_jobs:
            lines.append(f"* [{j['id']}] {j['type']} (started at {j['started_at']})")
        lines.append("")

    if scheduled_jobs:
        lines.append(_pluralise(len(scheduled_jobs), "scheduled job:"))
        lines.append("")
        for j in scheduled_jobs:
            lines.append(
                f"* [{j['id']}] {j['type']} (starting after {j['start_after']})"
            )
        lines.append("")

    if active_suppressions:
        lines.append(_pluralise(len(active_suppressions), "active suppression:"))
        lines.append("")
        for s in active_suppressions:
            lines.append(
                f"* [{s['id']}] {s['job_type']} (from {s['start_at']} to {s['end_at']})"
            )
        lines.append("")

    if scheduled_suppressions:
        lines.append(_pluralise(len(scheduled_suppressions), "scheduled suppression:"))
        lines.append("")
        for s in scheduled_suppressions:
            lines.append(
                f"* [{s['id']}] {s['job_type']} (from {s['start_at']} to {s['end_at']})"
            )
        lines.append("")

    if not (
        running_jobs or scheduled_jobs or active_suppressions or scheduled_suppressions
    ):
        lines.append("Nothing is happening")

    return "\n".join(lines).strip()


def _pluralise(n, noun):
    if n == 1:
        return f"There is 1 {noun}"
    else:
        return f"There are {n} {noun}s"


def user_has_permission(app, event, say, text, restricted_config, internal_user_ids):
    user_id = event["user"]
    # Internal users can do everything
    if user_id in internal_user_ids:
        return True
    # Unrestricted namespace jobs can be run by anyone
    namespace = text.split()[0]
    if not restricted_config[namespace]:
        return True
    # This is a job in a restricted namespace
    # There's a possibility this is a new user that we haven't registered in
    # internal_user_ids, so before rejecting them, fetch their info and
    # check that they really are a guest user.
    # It's unlikely that guest users will try to call bot commands often, so it's
    # not too much of a burden to run this check if/whenthey do
    if not user_is_guest(app.client, user_id):
        return True

    # User doesn't have permission, tell them so nicely before returning
    say(
        f":no_entry: Sorry, only Bennett Institute users are allowed to run `{namespace}` commands."
    )
    logger.info("Restricted command called by guest user", command=text, user=user_id)
    return False


def handle_command(app, message, say, slack_config, is_im):
    """
    Check if user has permission to run this command
    Give a thumbs-up to the message, and dispatch to another handler.
    """
    app.client.reactions_add(
        channel=message["channel"], timestamp=message["ts"], name="kuai-kuai-green"
    )

    handler = {
        "schedule_job": handle_schedule_job,
        "cancel_job": handle_cancel_job,
        "schedule_suppression": handle_schedule_suppression,
        "cancel_suppression": handle_cancel_suppression,
    }[slack_config["action"]]

    handler(message, say, slack_config, is_im)


def _remove_url_formatting(arg):
    """Slack formats URLs with angle brackets like <http://foo.com> or <http://foo.com|foo> (link text).
    We want to pass URLs on without the formatting, and drop the text as the job will most likely only involve the URL.

    """
    if arg.startswith("<http") and arg.endswith(">"):
        return arg[1:-1].split("|")[0]
    return arg


@log_call
def handle_schedule_job(message, say, slack_config, is_im=False):
    """Schedule a job."""
    match = slack_config["regex"].match(message["text"])
    job_args = dict(zip(slack_config["template_params"], match.groups()))
    deformatted_args = {k: _remove_url_formatting(v) for k, v in job_args.items()}
    logger.info("scheduling", msg=message)
    existing_job_is_running = scheduler.schedule_job(
        slack_config["job_type"],
        deformatted_args,
        channel=message["channel"],
        thread_ts=message.get("thread_ts"),
        delay_seconds=slack_config["delay_seconds"],
        is_im=is_im,
    )
    if existing_job_is_running:
        say(
            f"A `{slack_config['job_type']}` job has already started; request queued. "
            f"Type `@{settings.SLACK_APP_USERNAME} status` to see running jobs, and "
            f"`@{settings.SLACK_APP_USERNAME} remove job id [id]` to remove a blocking job."
        )


@log_call
def handle_cancel_job(message, say, slack_config, _is_im):
    """Cancel a job."""

    scheduler.cancel_job(slack_config["job_type"])


@log_call
def handle_schedule_suppression(message, say, slack_config, _is_im):
    """Schedule a suppression."""

    match = slack_config["regex"].match(message["text"])
    start_at = _get_datetime(match.groups()[0])
    end_at = _get_datetime(match.groups()[1])

    if start_at is None or end_at is None or start_at >= end_at:
        say(
            "Wrong time format - `[start_at]` and `[end_at]` must be HH:MM with `[start_at]` < `[end_at]`",
            thread_ts=message.get("thread_ts"),
        )
        return

    scheduler.schedule_suppression(slack_config["job_type"], start_at, end_at)
    say(
        f"{slack_config['job_type']} suppressed from {start_at} to {end_at}",
        thread_ts=message.get("ts"),
    )


@log_call
def handle_cancel_suppression(message, say, slack_config, _is_im):
    """Cancel a suppression."""

    scheduler.cancel_suppressions(slack_config["job_type"])
    say(
        f"{slack_config['job_type']} suppressions cancelled",
        thread_ts=message.get("ts"),
    )


@log_call
def handle_namespace_help(message, say, help_config, restricted):
    """Report commands available in namespace."""
    lines = []
    if restricted:
        lines.extend(
            [
                ":lock: These commands are only available to Bennett Institute users :lock:",
                "",
            ]
        )

    lines.extend(["The following commands are available:", ""])

    for command, help_ in help_config:
        lines.append(f"`{command}`: {help_}")

    say("\n".join(lines), thread_ts=message.get("thread_ts"))


@log_call
def handle_help(message, say, config, include_apology):
    """Report all available namespaces."""

    if include_apology:
        lines = ["I'm sorry, I didn't understand you", ""]
    else:
        lines = []
    lines.extend(["Commands in the following categories are available:", ""])

    for namespace in sorted(config["help"]):
        if config["restricted"][namespace]:
            namespace_line = f"* :lock: `{namespace}`"
        else:
            namespace_line = f"* `{namespace}`"
        if config["description"][namespace]:
            namespace_line += f": {config['description'][namespace]}"
        lines.append(namespace_line)

    if message["type"] == "app_mention":
        prefix = f"@{settings.SLACK_APP_USERNAME} "
    else:
        prefix = ""

    lines.append(
        f"Enter `{prefix}[category] help` (e.g. `{prefix}{random.choice(list(config['help']))} help`) for more help"
    )
    lines.append(f"Enter `{prefix}status` to see running and scheduled jobs")
    lines.append(
        f"Enter `{prefix}remove job id [id]` to remove a job; this will not "
        "cancel jobs that are in progress, but will let you retry a job that "
        "appears to have stalled."
    )
    say("\n".join(lines), thread_ts=message.get("thread_ts"))


def _get_datetime(hhmm):
    match = re.match(r"^(\d\d):?(\d\d)$", hhmm)
    if not match:
        return

    h = int(match.groups()[0])
    if not 0 <= h < 24:
        return

    m = int(match.groups()[1])
    if not 0 <= m < 60:
        return

    today = _now()
    return datetime(today.year, today.month, today.day, h, m, tzinfo=UTC)


def _now():
    return datetime.now(UTC)


if __name__ == "__main__":
    logger.info("running bennettbot.bot")
    run()
