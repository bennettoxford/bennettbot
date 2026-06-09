"""YAML-backed access to the shared repos/workflows/security config.

The config file lives at ``$WRITEABLE_DIR/repos_config.yaml`` so it can be
updated in production without a code change. See
``workspace/utils/repos_config.example.yaml`` for the expected shape.
"""

import functools

import yaml

from bennettbot import settings


CONFIG_PATH = settings.WRITEABLE_DIR / "repos_config.yaml"


@functools.cache
def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


config = load_config()

TEAMS = config["teams"]
REPOS = {
    repo: {"org": org, "team": team}
    for org, repos in config["repos"].items()
    for repo, team in repos.items()
}
IGNORED_WORKFLOWS = config["workflows"]["ignored_workflows"]
WORKFLOWS_KNOWN_TO_FAIL = config["workflows"]["workflows_known_to_fail"]
CUSTOM_WORKFLOWS_GROUPS = config["workflows"]["custom_groups"]


def get_repo_full_names_for_team(team: str) -> list[str]:
    return [f"{v['org']}/{repo}" for repo, v in REPOS.items() if v["team"] == team]


def get_repo_full_names_for_org(org: str) -> list[str]:
    return [f"{org}/{repo}" for repo, v in REPOS.items() if v["org"] == org]
