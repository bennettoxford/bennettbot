"""
Defines which jobs may be run, and how they can be invoked via Slack.
"""

import re
from operator import itemgetter

from bennettbot import settings


# fmt: off
raw_config = {
    "test": {
        "description": "Some commands to test things work",
        "jobs": {
            "read_poem": {
                "run_args_template": "cat poem",
                "report_stdout": True,
            },
            "hello_world": {
                "run_args_template": "python jobs.py",
                "report_stdout": True,
            },
            "hello_name": {
                "run_args_template": "python jobs.py --name={name}",
                "report_stdout": True,
            },
            "bad_job": {
                "run_args_template": "unknown command",
            }
        },
        "slack": [
            {
                "command": "read poem",
                "help": "read a poem",
                "action": "schedule_job",
                "job_type": "read_poem",
                "delay_seconds": 1,
            },
            {
                "command": "hello [name]",
                "help": "say hello to [name]",
                "action": "schedule_job",
                "job_type": "hello_name",
            },
            {
                "command": "hello",
                "help": "say hello",
                "action": "schedule_job",
                "job_type": "hello_world",
            },
            {
                "command": "bad job",
                "help": "a job that always errors",
                "action": "schedule_job",
                "job_type": "bad_job",
            },
        ],
    },
    "test-remote": {
        "description": "Some commands to test remote jobs work",
        # Note: we're making use of the fabfile config here to fetch a file
        # from a remote repo.
        # The file it's fetching is just a standard python file, not a fabfile,
        # but the job will fetch and write it as 'fabfile.py' irrespective of its
        # original name - so we need to run it with `python fabfile.py`
        "fabfile": "https://raw.githubusercontent.com/bennettoxford/bennettbot/main/workspace/test/jobs.py",
        "jobs": {
            "hello_world": {
                "run_args_template": "python fabfile.py",
                "report_stdout": True,
            },
        },
        "slack": [
            {
                "command": "hello",
                "help": "A test job that runs a script fetched from a remote location",
                "action": "schedule_job",
                "job_type": "hello_world",
            },
        ]
    },
    "fdaaa": {
        "restricted": True,
        "description": "Trials Tracker (https://fdaaa.trialstracker.net)",
        "fabfile": "https://raw.githubusercontent.com/ebmdatalab/clinicaltrials-act-tracker/main/fabfile.py",
        "jobs": {
            "deploy": {
                "run_args_template": "fab update:live",
            },
        },
        "slack": [
            {
                "command": "deploy",
                "help": "copy staging data to live site",
                "action": "schedule_job",
                "job_type": "deploy",
            },
        ],
    },
    "inbox": {
        "description": "Email inbox tools",
        "jobs": {
            "rota_report": {
                "run_args_template": "python jobs.py",
                "report_stdout": True,
                "report_format": "blocks",
            },
        },
        "slack": [
            {
                "command": "rota report",
                "help": "Report who's next on inbox checking duty",
                "action": "schedule_job",
                "job_type": "rota_report",
            },
        ],
    },
    "op": {
        "restricted": True,
        "description": "OpenPrescribing deployment and tools",
        "fabfile": "https://raw.githubusercontent.com/bennettoxford/openprescribing/main/fabfile.py",
        "default_channel": "#team-rap",
        "jobs": {
            "deploy": {
                "run_args_template": "fab deploy:production",
                "report_success": False,
            },
            "restart": {
                "run_args_template": "fab restart:production",
                "report_success": False,
            },
            "cache_clear": {
                "run_args_template": "fab clear_cloudflare"
            },
            "ncso_import": {
                "run_args_template": "fab call_management_command:fetch_and_import_ncso_concessions,production"
            },
            "ncso_report": {
                "run_args_template": "fab --hide=running,stdout,status call_management_command:summarise_ncso_concessions,production",
                "report_stdout": True,
            },
            "ncso_reconcile": {
                "run_args_template": "fab --hide=running,stdout,status call_management_command:reconcile_ncso_concession,production,{concession_id},{vmpp_id}",
                "report_stdout": True,
            },
            "ncso_send_alerts": {
                "run_args_template": "fab --hide=running,stdout,status call_management_command:send_ncso_concessions_alerts,production,--quiet",
                "report_stdout": True,
            },
            "import_measure_definition": {
                "run_args_template": "fab --hide=running,stdout,status call_management_command:import_measures,production,--print-confirmation,--definitions_only,--measure,{measure_id}",
                "report_stdout": True,
            },
            "recalculate_measure": {
                "run_args_template": "fab --hide=running,stdout,status call_management_command:import_measures,production,--print-confirmation,--measure,{measure_id}",
                "report_stdout": True,
            },
            "preview_measure": {
                "run_args_template": "fab --hide=running,stdout,status call_management_command:preview_measure,production,{github_measure_url}",
                "report_stdout": True,
            },
            "delete_preview": {
                "run_args_template": "fab --hide=running,stdout,status call_management_command:delete_measure,production,{measure_id}",
                "report_stdout": True,
            },
        },
        "slack": [
            {
                "command": "deploy",
                "help": "deploy to production after a 60s delay",
                "action": "schedule_job",
                "job_type": "deploy",
                "delay_seconds": 60,
            },
            {
                "command": "deploy now",
                "help": "deploy to production immediately",
                "action": "schedule_job",
                "job_type": "deploy",
            },
            {
                "command": "deploy cancel",
                "help": "cancel any pending production deploy",
                "action": "cancel_job",
                "job_type": "deploy",
            },
            {
                "command": "deploy suppress from [start_at] to [end_at]",
                "help": "suppress production deploys between these times today (times in UTC as 'HH:MM')",
                "action": "schedule_suppression",
                "job_type": "deploy",
            },
            {
                "command": "deploy suppress cancel",
                "help": "cancel suppression of production deploys",
                "action": "cancel_suppression",
                "job_type": "deploy",
            },
            {
                "command": "restart",
                "help": "restart production",
                "action": "schedule_job",
                "job_type": "restart",
            },
            {
                "command": "cache clear",
                "help": "clear Cloudflare cache",
                "action": "schedule_job",
                "job_type": "cache_clear",
            },
            {
                "command": "ncso import",
                "help": "import NCSO concessions",
                "action": "schedule_job",
                "job_type": "ncso_import",
            },
            {
                "command": "ncso report",
                "help": "show NCSO concession summary",
                "action": "schedule_job",
                "job_type": "ncso_report",
            },
            {
                "command": "ncso reconcile concession [concession_id] against vmpp [vmpp_id]",
                "help": "show NCSO concession summary",
                "action": "schedule_job",
                "job_type": "ncso_reconcile",
            },
            {
                "command": "ncso send alerts",
                "help": "send alerts for NCSO concessions",
                "action": "schedule_job",
                "job_type": "ncso_send_alerts",
            },
            {
                "command": "measures import [measure_id]",
                "help": "import measure definition",
                "action": "schedule_job",
                "job_type": "import_measure_definition",
            },
            {
                "command": "measures recalculate [measure_id]",
                "help": "recalculate measure values",
                "action": "schedule_job",
                "job_type": "recalculate_measure",
            },
            {
                "command": "measures preview [github_measure_url]",
                "help": "import hidden preview version of measure direct from Github",
                "action": "schedule_job",
                "job_type": "preview_measure",
            },
            {
                "command": "measures delete_preview [measure_id]",
                "help": "delete preview measure from site",
                "action": "schedule_job",
                "job_type": "delete_preview",
            }
        ],
    },
    "outputchecking": {
        "description": "Output Checking tools",
        "jobs": {
            "rota_report": {
                "run_args_template": "python jobs.py",
                "report_stdout": True,
                "report_format": "blocks",
            },
        },
        "slack": [
            {
                "command": "rota report",
                "help": "Report who's next on output checking duty",
                "action": "schedule_job",
                "job_type": "rota_report",
            },
        ],
    },
    "report": {
        "description": "Run GitHub Project board reports",
        "jobs": {
            "run_report": {
                "run_args_template": "python generate_report.py --project-num {project_number} --statuses {statuses}",
                "report_stdout": True,
                "report_format": "blocks",
            },
            "run_rap_report": {
                "run_args_template": "python generate_report.py --project-num 15 --statuses 'Under Review,Blocked,In Progress'",
                "report_stdout": True,
                "report_format": "blocks",
            },
            "run_rex_report": {
                "run_args_template": "python generate_report.py --project-num 14 --statuses 'In Progress,In Review,Blocked'",
                "report_stdout": True,
                "report_format": "blocks",
            },
        },
        "slack": [
            {
                "command": "board [project_number] [statuses]",
                "help": "Report GitHub project board. Provide multiple statuses separated by commas.",
                "action": "schedule_job",
                "job_type": "run_report",
            },
            {
                "command": "teamrap",
                "help": "Team RAP board report",
                "action": "schedule_job",
                "job_type": "run_rap_report",
            },
            {
                "command": "teamrex",
                "help": "Team REX board report",
                "action": "schedule_job",
                "job_type": "run_rex_report",
            },
        ]
    },
    "workflows": {
        "restricted": True,
        "description": "Report GitHub Actions workflow runs",
        "jobs": {
            "display_emoji_key": {
                "run_args_template": "python jobs.py key",
                "report_stdout": True,
                "report_format": "blocks",
            },
            "display_usage": {
                "run_args_template": "python jobs.py usage",
                "report_stdout": True,
            },
            "show": {
                "run_args_template": "python jobs.py show --target {target}",
                "report_stdout": True,
                "report_format": "blocks",
            },
            "show_all": {
                "run_args_template": "python jobs.py show",
                "report_stdout": True,
                "report_format": "blocks",
            },
            "show_failed": {
                "run_args_template": "python jobs.py show --target {target} --skip-successful",
                "report_stdout": True,
                "report_format": "blocks",
            },
            "show_failed_all": {
                "run_args_template": "python jobs.py show --skip-successful",
                "report_stdout": True,
                "report_format": "blocks",
            },
            "show_group": {
                "run_args_template": "python jobs.py show --group {group}",
                "report_stdout": True,
                "report_format": "blocks",
            },
        },
        "slack": [
            {
                "command": "key",
                "help": "Show the emoji key being used in the workflow summaries.",
                "action": "schedule_job",
                "job_type": "display_emoji_key",
            },
            {
                "command": "usage",
                "help": "Show help message for the `show [target]` and `show-failed [target]` commands.",
                "action": "schedule_job",
                "job_type": "display_usage",
            },
            {
                "command": "show",
                "help": "Summarise GitHub Actions workflow runs for repos in all organisations.",
                "action": "schedule_job",
                "job_type": "show_all",
            },
            {
                "command": "show-failed",
                "help": "Summarise unsuccessful GitHub Actions workflow runs for repos in all organisations.",
                "action": "schedule_job",
                "job_type": "show_failed_all",
            },
            {
                "command": "show [target]",
                "help": "Summarise GitHub Actions workflow runs for `target`. See `workflows usage` for valid `target` values.",
                "action": "schedule_job",
                "job_type": "show",
            },
            {
                "command": "show-failed [target]",
                "help": "Same as `show [target]`, but skips summarising repos whose runs are all successful.",
                "action": "schedule_job",
                "job_type": "show_failed",
            },
            {
                "command": "show-group [group]",
                "help": "Summarise GitHub Actions workflow runs for a custom defined group of workflows.",
                "action": "schedule_job",
                "job_type": "show_group",
            },
        ]
    },
    "techsupport": {
        "restricted": True,
        "description": "Tech Support out of office and rota",
        "jobs": {
            "out_of_office_on": {
                "run_args_template": "python jobs.py on {start_date} {end_date}",
                "report_stdout": True,
            },
            "out_of_office_off": {
                "run_args_template": "python jobs.py off",
                "report_stdout": True,
            },
            "out_of_office_status": {
                "run_args_template": "python jobs.py status",
                "report_stdout": True,
            },
            "rota_report": {
                "run_args_template": "python jobs.py rota",
                "report_stdout": True,
                "report_format": "blocks",
            },
        },
        "slack": [
            {
                "command": "ooo on from [start_date] to [end_date]",
                "help": "Set tech support out of office between these dates "
                        "(inclusive, in 'YYYY-MM-DD' format)",
                "action": "schedule_job",
                "job_type": "out_of_office_on",
            },
            {
                "command": "ooo off",
                "help": "Turn tech support out of office off",
                "action": "schedule_job",
                "job_type": "out_of_office_off",
            },
            {
                "command": "ooo status",
                "help": "Report current tech support out of office status",
                "action": "schedule_job",
                "job_type": "out_of_office_status",
            },
            {
                "command": "rota report",
                "help": "Report who's next on tech support duty",
                "action": "schedule_job",
                "job_type": "rota_report",
            },
        ],
    },
    "funding": {
        "restricted": True,
        "description": "Run funding reports",
        "jobs": {
            "generate_report": {
                "run_args_template": "python funding_report.py",
                "report_stdout": True,
                "report_format": "blocks",
            }
        },
        "slack": [
            {
                "command": "report",
                "help": "generate funding report",
                "action": "schedule_job",
                "job_type": "generate_report",
            },
        ],
    },
    "showlogs": {
        "description": "Show content of logs from bot commands",
        "jobs": {
            "tail": {
                "run_args_template": "/bin/bash show.sh -t -f {logtype} {logdir}",
                "report_stdout": True,
                "report_format": "code",
            },
            "head": {
                "run_args_template": "/bin/bash show.sh -h -f {logtype} {logdir}",
                "report_stdout": True,
                "report_format": "code",
            },
            "all": {
                "run_args_template": "/bin/bash show.sh -a -f {logtype} {logdir}",
                "report_stdout": True,
                "report_format": "code",
            },
        },
        "slack": [
            {
                "command": "tail [logtype] [logdir]",
                "help": 'Show tail of a [logtype] file ("error" or "output") located in [logdir] (a path to a log directory as reported by a failed job).',
                "action": "schedule_job",
                "job_type": "tail",
            },
            {
                "command": "head [logtype] [logdir]",
                "help": 'Show head of a [logtype] file ("error" or "output") located in [logdir] (a path to a log directory as reported by a failed job).',
                "action": "schedule_job",
                "job_type": "head",
            },
            {
                "command": "all [logtype] [logdir]",
                "help": (
                    'Show tail of a [logtype] file ("error" or "output") located in [logdir] (a path to a log directory as reported by a failed job).',
                    "Note this may return a lot of output split over multiple slack messages."
                ),
                "action": "schedule_job",
                "job_type": "all",
            },
        ],
    },
    "dependabot": {
        "description": "The Team REX Dependabot rota",
        "jobs": {
            "rota_report": {
                "run_args_template": "python jobs.py",
                "report_stdout": True,
                "report_format": "blocks",
            },
        },
        "slack": [
            {
                "command": "rota report",
                "help": "Report who's next on Dependabot PR checking duty",
                "action": "schedule_job",
                "job_type": "rota_report",
            },
        ],
    },
    "codespaces": {
        "description": "Codespaces monitoring tools",
        "jobs": {
            "at_risk": {
                "run_args_template": "python codespaces.py {threshold_in_days}",
                "report_stdout": True,
                "report_format": "blocks",
            },
        },
        "slack": [
            {
                "command": "at risk [threshold_in_days]",
                "help": "Report Codespaces at risk of being deleted",
                "action": "schedule_job",
                "job_type": "at_risk",
                "delay_seconds": 0,
            },
        ],
    },
    "standup": {
        "description": "Show the standup rota for Team REX",
        "jobs": {
            "weekly": {
                "run_args_template": "python jobs.py weekly",
                "report_stdout": True,
                "report_format": "blocks",
            },
            "daily": {
                "run_args_template": "python jobs.py daily {day_of_week}",
                "report_stdout": True,
                "report_format": "blocks",
            },
        },
        "slack": [
            {
                "command": "weekly",
                "help": "Show the weekly standup rota for Team REX",
                "action": "schedule_job",
                "job_type": "weekly",
                "delay_seconds": 0,
            },
            {
                "command": "daily [day_of_week]",
                "help": "Show the daily standup rota for Team REX",
                "action": "schedule_job",
                "job_type": "daily",
                "delay_seconds": 0,
            },
        ],
    },
}
# fmt: on


def build_config(raw_config):
    """Convert raw_config into something that's easier to work with.

    See test_job_configs for an example.
    """

    config = {
        "jobs": {},
        "slack": [],
        "description": {},
        "help": {},
        "fabfiles": {},
        "workspace_dir": {},
        "restricted": {},
        "default_channel": {},
    }

    for namespace in raw_config:
        if "_" in namespace:  # pragma: no cover
            raise RuntimeError("Namespaces must not contain underscores")

        config["description"][namespace] = raw_config[namespace].get("description", "")
        config["restricted"][namespace] = raw_config[namespace].get("restricted", False)
        config["default_channel"][namespace] = raw_config[namespace].get(
            "default_channel", "#tech"
        )

        helps = []

        for job_type, job_config in raw_config[namespace]["jobs"].items():
            job_config["report_stdout"] = job_config.get("report_stdout", False)
            job_config["report_format"] = job_config.get("report_format", "text")
            job_config["report_success"] = job_config.get("report_success", True)
            namespaced_job_type = f"{namespace}_{job_type}"
            validate_job_config(namespaced_job_type, job_config)
            config["jobs"][namespaced_job_type] = job_config

        for slack_config in raw_config[namespace]["slack"]:
            command = f"{namespace} {slack_config['command']}"
            slack_config["command"] = command
            slack_config["job_type"] = f"{namespace}_{slack_config['job_type']}"
            slack_config["regex"] = build_regex_from_command(command)
            slack_config["template_params"] = get_template_params(command)
            slack_config["delay_seconds"] = slack_config.get("delay_seconds", 0)

            validate_slack_config(slack_config)
            config["slack"].append(slack_config)

            helps.append([command, slack_config["help"]])

        config["help"][namespace] = sorted(helps)

        if "fabfile" in raw_config[namespace]:
            config["fabfiles"][namespace] = raw_config[namespace]["fabfile"]

        if (settings.WORKSPACE_DIR / namespace).exists():
            config["workspace_dir"][namespace] = settings.WORKSPACE_DIR
        else:
            config["workspace_dir"][namespace] = settings.WRITEABLE_WORKSPACE_DIR

    config["slack"] = sorted(config["slack"], key=itemgetter("command"))

    for slack_config in config["slack"]:
        command = slack_config["command"]
        job_type = config["jobs"].get(slack_config["job_type"])
        if not job_type:
            msg = f"Slack command {command} references unknown job type {slack_config['job_type']}"
            raise RuntimeError(msg)
        if slack_config["action"] == "schedule_job":
            validate_job_and_slack_params_match(
                command, slack_config["template_params"], job_type["run_args_template"]
            )
    return config


def build_regex_from_command(command):
    """Convert Slack command into regex that matches command.

    >>> build_pattern_from_command("say [greeting] to [name]")
    re.compile("^say (.+?) to (.+?)$")
    """

    pattern = "^" + re.sub(r"\[\w+\]", r"(.+?)", command) + "$"
    return re.compile(pattern)


def get_template_params(command, wrapper="[]"):
    """Extract parameters from a Slack command or arguments template.

    >>> get_template_params("say [greeting] to [name]")
    ["greeting", "name"]
    >>> get_template_params("say {greeting} to {name}", wrapper="{}")
    ["greeting", "name"]
    """
    start, end = wrapper
    regex = f"{re.escape(start)}(\\w+){re.escape(end)}"
    return re.findall(regex, command)


def validate_job_config(job_type, job_config):
    """Validate that job_config contains expected keys."""

    expected_keys = {
        "run_args_template",
        "report_stdout",
        "report_format",
        "report_success",
    }

    if missing_keys := (expected_keys - job_config.keys()):
        msg = f"Job {job_type} is missing keys {missing_keys}"
        raise RuntimeError(msg)

    if extra_keys := (job_config.keys() - expected_keys):
        msg = f"Job {job_type} has extra keys {extra_keys}"
        raise RuntimeError(msg)

    if job_config["report_format"] not in ["text", "blocks", "code", "file"]:
        msg = (
            f"Job {job_type} has an invalid report_format; must be "
            "one of 'text', 'blocks', 'code' or 'file'"
        )
        raise RuntimeError(msg)


def validate_slack_config(slack_config):
    """Validate that slack_config contains expected keys."""

    expected_keys = {
        "command",
        "help",
        "action",
        "job_type",
        "regex",
        "template_params",
        "delay_seconds",
    }

    command = slack_config["command"]

    if missing_keys := (expected_keys - slack_config.keys()):
        msg = f"Slack command `{command}` is missing keys {missing_keys}"
        raise RuntimeError(msg)

    if extra_keys := (slack_config.keys() - expected_keys):
        msg = f"Slack command `{command}` has extra keys {extra_keys}"
        raise RuntimeError(msg)


def validate_job_and_slack_params_match(command, params, run_args_template):
    run_args = get_template_params(run_args_template, wrapper="{}")
    if set(params) != set(run_args):
        msg = f"Slack command {command} does not match the template {run_args_template}"
        raise RuntimeError(msg)


config = build_config(raw_config)
