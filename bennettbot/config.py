import re

from . import settings


def get_support_config(channels=None):
    channels = channels or {}
    return {
        "tech-support": {
            "keyword": "tech-support",
            # Use the support setting (a channel name or channel ID) to get the channel.
            # We first attempt to retrieve channel ID from the channels dict (if provided),
            # otherwise we default to using the setting value as is.
            "support_channel": channels.get(
                settings.SLACK_TECH_SUPPORT_CHANNEL, settings.SLACK_TECH_SUPPORT_CHANNEL
            ),
            # Match "tech-support" as a word (treating hyphens as word characters), except if
            # it's preceded by a slash to avoid matching it in URLs
            "regex": re.compile(r".*(^|[^\w\-/])tech-support($|[^\w\-]).*", flags=re.I),
            "reaction": "sos",
        },
        "bennett-admins": {
            "keyword": "bennett-admins",
            # Use the support setting (a channel name or channel ID) to get the channel.
            # We first attempt to retrieve channel ID from the channels dict (if provided),
            # otherwise we default to using the setting value as is.
            "support_channel": channels.get(
                settings.SLACK_BENNETT_ADMINS_CHANNEL,
                settings.SLACK_BENNETT_ADMINS_CHANNEL,
            ),
            # Match any of "bennett-admins" or "bennet-admins" or "bennett-admin" or
            # "bennet-admin" as a word (treating hyphens as word characters), except if
            # it's preceded by a slash to avoid matching it in URLs
            "regex": re.compile(
                r".*(^|[^\w\-/])bennett?-admins?($|[^\w\-]).*", flags=re.I
            ),
            "reaction": "flamingo",
        },
    }
