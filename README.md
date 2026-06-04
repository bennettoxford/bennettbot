# bennettbot

bennettbot is a service for running jobs in response to Slack commands and GitHub webhooks.

A job runs a bash command in a given directory.
Jobs are organised by namespace, and are defined in `job_configs.py`.
See [Configuring jobs](#configuring-jobs) below for further details.

There are three moving parts:

* `bot.py` -- a [slack bolt app](https://github.com/slackapi/bolt-python) that listens for jobs via Slack commands (see also [Slack docs](https://api.slack.com/bolt))
* `webserver/` -- a Flask app that listens for jobs via webhooks from GitHub
* `dispatcher.py` -- a Python script that sits in a loop and runs the jobs

They communicate via a table in a SQLite database that acts as a simple job queue.
The database schema is in `connection.py`, and functions for putting jobs onto the queue (and taking them off again) are in `scheduler.py`.


## Configuring jobs

A job runs a bash command in a particular job directory or namespace. Each job
creates a log folder where output and error from the command is written to files named
`stdout` and `stderr` respectively. If a job is to be reported to slack, the content
of `stdout` is read in and posted as the slack message in
[one of the available formats](#output-format);

Jobs are defined in `job_configs.py`. A dict called `raw_config`
defines which jobs may be run, and how they can be invoked via Slack.

Each key in `raw_config` refers to a category of jobs (the job namespace), and maps to a dict that defines jobs in that category in the following format:

```
{
    "description": "", # Optional description of this category of jobs
    "restricted": boolean, default=False  # restrict this category to internal users only
    "fabfile": "",  # for fabric commands, location on github of fabfile
    "jobs": {
        # this defines the individual jobs
        <job_type>: {
            "run_args_template": "",  # template of bash command to be run
            "report_stdout": boolean, default=False,  # whether to report contents of stdout to slack
            "report_success": boolean, default=True,  # whether to report success to slack
            "report_format": "text/blocks/code/file",  # format of slack report, plain text, blocks, code or file upload (default="text")
            "suppress_empty": boolean, default=False,  # if True and stdout is empty, post nothing to slack (instead of the default "No output found" message); useful for scheduled check-style jobs that should only ping when there's something to report
        }
    }
    "slack": [
        # this defines the slack commands used to run the jobs
        {
            "command": "",  # the slack command, with any parameters in []
            "help": "",  # help text,
            "action": "schedule_job", # what this slack command does)
            "job_type": <job_type>,  # reference to key in jobs
            "delay_seconds": 0
        }
    ]
}
```

Note: the slack `"action"` can also take the values "cancel_job",
"schedule_suppression" or "cancel_suppression", however currently these only apply
to OpenPrescribing jobs. New jobs will likely only require `"schedule_job"` slack
commands.


## Example job config

### Simple bash command

The following config creates one job namespace ("test") with one
slack command ("say hello"), which schedules the "hello" job with a
1 second delay.

```
raw_config = {
    "test": {
        "jobs": {
            "hello": {
                "run_args_template": "echo Hello",
                "report_stdout": True,
            },
        },
        "slack": [
            {
                "command": "say hello",
                "help": "Says hello",
                "action": "schedule_job",
                "job_type": "hello",
                "delay_seconds": 1,
            },
        ]
    }
}
```
Call this with `@BennettBot test say hello`; after a 1 second delay, BennettBot
will run `echo hello`, write the output to its log folder, and report the
contents to slack.


### Command with parameters

Jobs and commands can be parameterised. A slack command uses square brackets
to indicate an expected parameter, which will be templated into the same named
parameter in `run_args_template`.

```
raw_config = {
    "example": {
        "jobs": {
            "hello_to": {
                "run_args_template": "echo Hello {name}",
                "report_stdout": True,
            },
        },
        "slack": [
            {
                "command": "say hello [name]",
                "help": "Says hello to [name]",
                "action": "schedule_job",
                "job_type": "hello_to",
            },
        ]
    }
}
```
Call this with e.g. `@BennettBot example say hello Bob`; the name string will be
formatted into the run command to `echo hello Bob`.

### Python scripts

A job simply runs a bash command in its namespace folder
(in `workspace/<namespace>`). To run a python script, create the script in
`workspace/<namespace>`. E.g. if we have a script at `example/do_job.py`, the
following config will run it and report the output to slack:

```
raw_config = {
    "example": {
        "jobs": {
            "do_python": {
                "run_args_template": "python do_job.py --some-arg {some_arg}",
                "report_stdout": True,
            },
        },
        "slack": [
            {
                "command": "do python [some_arg]",
                "help": "Runs a python script with --some-arg [some_arg]",
                "action": "schedule_job",
                "job_type": "do_python",
            },
        ]
    }
}
```

Some caveats:
- Note that if the job is expected to report to slack, it must print output to stdout.
- Scripts run in a job have access to all environment variables, but they do not have
  access to the app itself, so e.g. can't use `bennettbot.settings`; use the environment
  variables these are based on instead.
- PYTHONPATH is set to the root directory of the application, so scripts can access other
  modules.
- If a script needs to write to the filesystem, it MUST write to a location within
  `WRITEABLE_DIR`, not its namespace directory.

### Fabric jobs

Jobs that run fabric commands do not have a workspace namespace directory in this repo;
instead they specify a URL to a fabfile that will be fetched and run.

E.g.
```
raw_config = {
    "example": {
        "fabfile": "https://location/of/fabfile.py",
        "jobs": {
            "do_fab": {
                "run_args_template": "fab <command>",
                "report_success": True,
            },
        },
        ...
    }
}
```

### Output format

The default output format for any job that reports to Slack is plain text. You can
get fancier output by using Slack's
[block format](https://api.slack.com/methods/chat.postMessage#arg_blocks).

This means that any scripts will need to output json (an array of valid block objects)
and print it to stdout.

Slack has a helpful [block kit builder](https://app.slack.com/block-kit-builder) that
can be used for checking your block output is valid.

Note that slack messages can contain a maximum of 50 blocks.

The output can also be `file`; this will be posted as a file snippet instead
of a message.

Finally, output can also be formatted as code; this will just wrap a plain text
message in triple backticks for code formatting in Slack. If the message is
too long for a single Slack message (4000 characters), it will be uploaded
as a file snippet instead.

## Deployment docs

Please see the [additional information](DEPLOY.md).


## Developer docs

Please see the [additional information](DEVELOPERS.md).
