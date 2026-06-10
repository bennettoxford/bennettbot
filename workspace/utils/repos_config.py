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


def teams() -> list[str]:
    return load_config()["teams"]


def org_shorthands() -> dict:
    return load_config()["shorthands"]["orgs"]


def team_shorthands() -> dict:
    return load_config()["shorthands"]["teams"]


def repos_by_org() -> dict:
    """{org: {repo_name: team}} — the on-disk shape."""
    return load_config()["repos"]


def all_repo_names() -> list[str]:
    return [repo for repos in repos_by_org().values() for repo in repos]


def find_orgs_for_repo(name: str) -> list[str]:
    """All orgs whose YAML entry includes a repo with this name."""
    return [org for org, repos in repos_by_org().items() if name in repos]


def workflows_config() -> dict:
    return load_config()["workflows"]


def get_repo_full_names_for_team(team: str) -> list[str]:
    return [
        f"{org}/{repo}"
        for org, repos in repos_by_org().items()
        for repo, repo_team in repos.items()
        if repo_team == team
    ]


def get_repo_full_names_for_org(org: str) -> list[str]:
    return [f"{org}/{repo}" for repo in repos_by_org().get(org, {})]
