from bennettbot.job_configs import build_config


# fmt: off
raw_config = {
    "test": {
        "jobs": {
            "python_version": {
                "run_args_template": 'python -c "import platform; print(platform.python_version())"',
            },
            "good_job": {
                "run_args_template": "cat poem",
            },
            "parameterised_job": {
                "run_args_template": "cp poem poem{n}; cat poem{n}; rm poem{n}",
            },
            "parameterised_job_2": {
                "run_args_template": "echo {thing_to_echo}",
            },
            "reported_job": {
                "run_args_template": "cat poem",
                "report_stdout": True,
            },
            "unreported_job": {
                "run_args_template": "cat poem",
                "report_success": False,
            },
            "bad_job": {
                "run_args_template": "cat no-poem",
            },
            "unsupported_bad_job": {
                "run_args_template": "cat no-poem",
                "call_tech_support_on_error": False,
            },
            "really_bad_job": {
                "run_args_template": "dog poem",
            },
            "job_with_url": {
                "run_args_template": "curl {url}",
            },
            "good_python_job": {
                "run_args_template": "python jobs.py hello_world",
                "report_stdout": True
            },
            "bad_python_job": {
                "run_args_template": "python unk.py",
                "report_stdout": True
            },
            "parameterised_python_job": {
                "run_args_template": "python jobs.py hello_world --name {name}",
                "report_stdout": True
            },
            "good_python_job_with_blocks": {
                "run_args_template": "python jobs.py hello_world_blocks",
                "report_stdout": True,
                "report_format": "blocks"
            },
            "bad_python_job_with_blocks": {
                "run_args_template": "python jobs.py hello_world_blocks_error",
                "report_stdout": True,
                "report_format": "blocks"
            },
            "python_job_no_output": {
                "run_args_template": "python jobs.py hello_world_no_output",
                "report_stdout": True,
            },
            "python_job_long_code_output": {
                "run_args_template": "python jobs.py long_code_output",
                "report_format": "code",
                "report_stdout": True,
            },
            "good_job_with_code": {
                "run_args_template": "cat poem",
                "report_stdout": True,
                "report_format": "code"
            },
            "good_job_with_file": {
                "run_args_template": "cat poem",
                "report_stdout": True,
                "report_format": "file"
            },
        },
        "slack": [
            {
                "command": "do good job",
                "help": "do the good job",
                "action": "schedule_job",
                "job_type": "good_job",
                "delay_seconds": 60,
            },
            {
                "command": "do job [n]",
                "help": "do the parameterised job",
                "action": "schedule_job",
                "job_type": "parameterised_job",
                "delay_seconds": 60,
            },
            {
                "command": "cancel job",
                "help": "cancel the job",
                "action": "cancel_job",
                "job_type": "good_job",
            },
            {
                "command": "suppress job from [start_at] to [end_at]",
                "help": "suppress the job",
                "action": "schedule_suppression",
                "job_type": "good_job",
            },
            {
                "command": "cancel suppression",
                "help": "don't suppress the job",
                "action": "cancel_suppression",
                "job_type": "good_job",
            },
            {
                "command": "do url [url]",
                "help": "do a job with a url",
                "action": "schedule_job",
                "job_type": "job_with_url",
                "delay_seconds": 0,
            },
            {
                "command": "do python job",
                "help": "run a python function",
                "action": "schedule_job",
                "job_type": "good_python_job",
                "delay_seconds": 0,
            },
            {
                "command": "do python job [name]",
                "help": "run a python function",
                "action": "schedule_job",
                "job_type": "parameterised_python_job",
                "delay_seconds": 0,
            },
            {
                "command": "do python blocks job",
                "help": "run a python function",
                "action": "schedule_job",
                "job_type": "good_python_job_with_blocks",
                "delay_seconds": 0,
            },
        ],
    },
    "test1": {
        "description": "Test description",
        "jobs": {
            "good_job": {
                "run_args_template": "cat poem",
            },
        },
        "slack": [],
    },
    "testrestricted": {
        "restricted": True,
        "jobs": {
            "good_job": {
                "run_args_template": "cat poem",
            },
        },
        "slack": [
            {
                "command": "do job",
                "help": "do the restricted job",
                "action": "schedule_job",
                "job_type": "good_job",
            }
        ],
    }
}
# fmt: on


config = build_config(raw_config)
