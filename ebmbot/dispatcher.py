import json
import os
import shlex
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from multiprocessing import Process
from pathlib import Path

import requests

from . import job_configs, scheduler, settings
from .logger import logger
from .slack import notify_slack, slack_web_client


def run():  # pragma: no cover
    """Start the dispatcher and the message checker running."""
    slack_client = slack_web_client(token_type="bot")
    checker = MessageChecker(slack_client, slack_web_client(token_type="user"))
    checker.run_check()
    while True:
        run_once(slack_client, job_configs.config)
        time.sleep(1)


def run_once(slack_client, config):
    """Clear any expired suppressions, then start a new subprocess for each
    available job.

    We collect and return started processes so that we can wait for them to
    finish in tests before asserting the tests have done anything.
    """
    scheduler.remove_expired_suppressions()

    processes = []
    while True:
        job_id = scheduler.reserve_job()
        if job_id is None:
            break
        job_dispatcher = JobDispatcher(slack_client, job_id, config)
        processes.append(job_dispatcher.start_job())

    return processes


class JobDispatcher:
    def __init__(self, slack_client, job_id, config):
        logger.info("starting job", job_id=job_id)
        self.slack_client = slack_client
        self.job = scheduler.get_job(job_id)
        self.job_config = config["jobs"][self.job["type"]]

        self.namespace = self.job["type"].split("_")[0]
        self.workspace_dir = config["workspace_dir"][self.namespace]
        self.cwd = self.workspace_dir / self.namespace
        self.fabfile_url = config["fabfiles"].get(self.namespace)
        escaped_args = {k: shlex.quote(v) for k, v in self.job["args"].items()}
        self.run_args = self.job_config["run_args_template"].format(**escaped_args)

    def start_job(self):
        """Start running the job in a new subprocess."""

        p = Process(target=self.do_job)
        p.start()
        return p

    def do_job(self):
        """Run the job."""

        self.set_up_cwd()
        self.set_up_log_dir()
        self.notify_start()
        rc = self.run_command()
        scheduler.mark_job_done(self.job["id"])
        self.notify_end(rc)

    def run_command(self):
        """Run the command, writing stdout/stderr to separate files."""

        logger.info("run_command {")
        logger.info(
            "run_command",
            run_args=self.run_args,
            cwd=self.cwd,
            stdout_path=self.stdout_path,
            stderr_path=self.stdout_path,
        )

        with open(self.stdout_path, "w") as stdout, open(
            self.stderr_path, "w"
        ) as stderr:
            try:
                rv = subprocess.run(
                    self.run_args,
                    cwd=self.cwd,
                    stdout=stdout,
                    stderr=stderr,
                    env={**os.environ, "PYTHONPATH": settings.APPLICATION_ROOT},
                    shell=True,
                )
                rc = rv.returncode
            except Exception:  # pragma: no cover
                traceback.print_exception(*sys.exc_info(), file=stderr)
                rc = -1

        logger.info("run_command", rc=rc)
        logger.info("run_command }")
        return rc

    def notify_start(self):
        """Send notification that command is about to start."""

        msg = f"Command `{self.job['type']}` about to start"
        notify_slack(self.slack_client, settings.SLACK_LOGS_CHANNEL, msg)

    def notify_end(self, rc):
        """Send notification that command has ended, reporting stdout if
        required."""

        error = False
        if rc == 0:
            if self.job_config["report_stdout"]:
                with open(self.stdout_path) as f:
                    if self.job_config["report_format"] == "blocks":
                        msg = json.load(f)
                    else:
                        msg = f.read()
                    if not msg:
                        msg = f"No output found for command `{self.job['type']}`"
            elif self.job_config["report_success"]:
                msg = f"Command `{self.job['type']}` succeeded"
            else:
                return
        else:
            msg = (
                f"Command `{self.job['type']}` failed.\n"
                f"Find logs in {self.host_log_dir} on dokku3.\n"
                f"Or check logs here with `showlogs head/tail/all`, e.g.\n"
                f"* `@{settings.SLACK_APP_USERNAME} showlogs tail error {self.host_log_dir}`\n"
                f"* `@{settings.SLACK_APP_USERNAME} showlogs all output {self.host_log_dir}`\n"
            )
            if not self.job["is_im"]:
                msg += "\nCalling tech-support."
            error = True

        slack_message = notify_slack(
            self.slack_client,
            self.job["channel"],
            msg,
            thread_ts=self.job["thread_ts"],
            message_format=self.job_config["report_format"] if rc == 0 else "text",
        )
        if error and not self.job["is_im"]:
            # If the command failed, repost it to tech-support
            # Don't repost to tech-support if we're in a DM with the bot, because no-one
            # else will be able to read the reposted message
            # Note that the bot won't register messages from itself, so we can't just
            # rely on the tech-support listener
            message_url = self.slack_client.chat_getPermalink(
                channel=slack_message["channel"], message_ts=slack_message["ts"]
            )["permalink"]
            self.slack_client.chat_postMessage(
                channel=settings.SLACK_TECH_SUPPORT_CHANNEL, text=message_url
            )

    def set_up_cwd(self):
        """Ensure cwd exists, and maybe refresh fabfile."""
        self.cwd.mkdir(parents=True, exist_ok=True)

        if self.fabfile_url:  # pragma: no cover
            self.update_fabfile()

    def update_fabfile(self):  # pragma: no cover
        """Retreive latest version of fabfile.py, notifying Slack if this fails.

        Not tested out of developer laziness.
        """

        try:
            rsp = requests.get(self.fabfile_url)
            rsp.raise_for_status()
        except requests.RequestException as e:
            msg = f"Could not refresh {self.fabfile_url}: {e}"
            notify_slack(self.slack_client, settings.SLACK_LOGS_CHANNEL, msg)
            return

        with open(self.cwd / "fabfile.py", "w") as f:
            f.write(rsp.text)

    def set_up_log_dir(self):
        """Create directory for recording stdout/stderr."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        job_log_path = Path(self.job["type"]) / timestamp
        self.log_dir = settings.LOGS_DIR / job_log_path
        self.host_log_dir = settings.HOST_LOGS_DIR / job_log_path
        self.stdout_path = self.log_dir / "stdout"
        self.stderr_path = self.log_dir / "stderr"
        self.log_dir.mkdir(parents=True, exist_ok=True)


class MessageChecker:
    def __init__(self, bot_slack_client, user_slack_client):
        # The MessageChecker needs both a slack client with a bot token
        # (for fetching channel info, and posting/reacting as the bod)
        # and a client with a user token for the search messages endpoint
        # https://api.slack.com/methods/search.messages
        self.bot_slack_client = bot_slack_client
        self.user_slack_client = user_slack_client

        self.config = {
            "tech-support": {
                "reaction": "sos",
                "channel": settings.SLACK_TECH_SUPPORT_CHANNEL,
            },
            "bennett-admins": {
                "reaction": "flamingo",
                "channel": settings.SLACK_BENNETT_ADMINS_CHANNEL,
            },
        }

    def run_check(self):  # pragma: no cover
        """Start running the check in a new subprocess."""
        p = Process(target=self.do_check)
        p.start()
        return p

    def do_check(self, run_fn=lambda: True, delay=10):  # pragma: no branch
        # In production, we want this check to run forever. Using a
        # function means that we can test it on a finite number of loops.
        # Note that the message search endpoint is a tier2 endpoint and is
        # rate limited at around 20 calls per min
        # https://api.slack.com/apis/rate-limits#tier_t2
        # A 10s delay should be safe for our 2 calls per loop
        while run_fn():
            today = datetime.today()
            yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
            tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
            for keyword in self.config:
                self.check_messages(keyword, tomorrow, yesterday)
            time.sleep(delay)

    def check_messages(self, keyword, before, after):
        logger.debug("Checking %s messages", keyword)
        reaction = self.config[keyword]["reaction"]
        channel = self.config[keyword]["channel"]
        messages = self.user_slack_client.search_messages(
            query=(
                # Search for messages with the keyword but without the expected reaction
                f"{keyword} -has::{reaction}: "
                # exclude messages in the channel itself
                f"-in:#{channel} "
                # exclude messages from the bot
                f"-from:@{settings.SLACK_APP_USERNAME} "
                # exclude DMs as the auto-responders don't respond to these anyway
                f"-is:dm "
                # only include messages from today
                f"before:{before} after:{after}"
            )
        )["messages"]["matches"]
        for message in messages:
            if keyword not in message["text"]:
                # Skip this message as it doesn't itself contain the magic keyword.
                # It's likely to be a forwarded message or a copy/pasted link.
                # The re-posted text appears in a search, but we only want to
                # react to original messages.
                continue
            logger.info(
                "Found unreacted message", keyword=keyword, message=message["text"]
            )
            # add reaction
            self.bot_slack_client.reactions_add(
                channel=message["channel"]["id"], timestamp=message["ts"], name=reaction
            )
            # repost the message url to relevant channel
            message_url = self.bot_slack_client.chat_getPermalink(
                channel=message["channel"]["id"], message_ts=message["ts"]
            )["permalink"]
            notify_slack(self.bot_slack_client, channel, message_url)


if __name__ == "__main__":
    logger.info("running ebmbot.dispatcher")
    run()
