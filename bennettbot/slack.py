from time import sleep

from slack_sdk import WebClient

from bennettbot import settings
from workspace.utils.blocks import get_basic_header_and_text_blocks, truncate_text

from .logger import logger


def slack_web_client(token_type="bot"):
    match token_type:
        case "bot":
            token = settings.SLACK_BOT_TOKEN
        case "user":
            token = settings.SLACK_BOT_USER_TOKEN
        case _:
            assert False, "Unknown token type"
    token = (
        settings.SLACK_BOT_TOKEN
        if token_type == "bot"
        else settings.SLACK_BOT_USER_TOKEN
    )
    return WebClient(token=token)


def notify_slack(
    slack_client,
    channel,
    message_text,
    thread_ts=None,
    message_format=None,
    retry_delay=1,
):
    """Send message to Slack."""
    # The message text can be either a string or blocks (a list of dicts),
    # so stringify it for text arg and logs
    message_string = str(message_text)
    msg_kwargs = {"text": message_string, "thread_ts": thread_ts, "channel": channel}
    if message_format == "blocks":
        msg_kwargs["blocks"] = message_text
        # Block-based messages (reports, rotas etc.) often link to docs/repos as
        # reference - the unfurled previews are noisy, so suppress them.
        msg_kwargs["unfurl_links"] = False
        msg_kwargs["unfurl_media"] = False

    # Truncate message text for log to the first 500 characters
    log_message_text = message_string[:500]
    if len(log_message_text) < len(message_string):
        log_message_text += " (truncated)"

    logger.info(
        "Sending message",
        channel=channel,
        message=log_message_text,
        thread_ts=thread_ts,
    )
    # If messages are longer than 4000 characters, Slack will split them over
    # multiple messages. This breaks code formatting, so if a message with code
    # format is long, we upload it as a file snippet instead
    if message_format == "code":
        if len(message_text) > 3990:
            message_format = "file"
        else:
            msg_kwargs["text"] = f"```{msg_kwargs['text']}```"

    # In case of any unexpected transient exception posting to slack, retry up to
    # MAX_SLACK_NOTIFY_RETRIES times (default 2) and then report and log the error,
    # to avoid errors in scheduled jobs.
    retry_attempt = 0
    error = None
    while True:
        try:
            if message_format == "file":
                resp = slack_client.files_upload_v2(content=message_text, **msg_kwargs)
            else:
                resp = slack_client.chat_postMessage(**msg_kwargs)
            return resp.data
        except Exception as err:
            retry_attempt += 1
            error = err

        if retry_attempt > settings.MAX_SLACK_NOTIFY_RETRIES:
            break
        sleep(retry_delay)

    # The message has failed to post.
    # Modify the Slack message to report the error and try posting it to the channel
    header_text = "Could not notify slack"
    try:
        msg_kwargs["text"] = header_text
        msg_kwargs["blocks"] = get_slack_error_blocks(
            header_text, message_text, error=error
        )
        slack_client.chat_postMessage(**msg_kwargs)
    except Exception:
        # Not even the error message could not be posted to Slack, so
        pass
    finally:
        # Log the error
        logger.error(
            header_text,
            channel=channel,
            message=message_text,
            thread_ts=thread_ts,
            error=error,
        )


def get_slack_error_blocks(header_text, message_text, error):
    return get_basic_header_and_text_blocks(
        header_text=header_text,
        texts=[
            "Slack encountered the error",
            f"```{truncate_text(str(error), max_len=2994)}```",
            "when trying to post the following message:",
            f"```{truncate_text(message_text, max_len=2994)}```",
        ],
    )
