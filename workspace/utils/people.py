import functools
from dataclasses import dataclass

import yaml

from bennettbot import settings


CONFIG_PATH = settings.WRITEABLE_DIR / "people_config.yaml"


@dataclass(order=True)
class Person:
    github_username: str
    slack_username: str
    # Optional because this is mostly set in _build_people().
    human_readable: str = ""

    @property
    def formatted_slack_username(self) -> str:
        return f"<@{self.slack_username}>"


def _validate_team_members_exist(config: dict) -> None:
    known_people = set(config.get("people", {}))
    for team_name, keys in config.get("teams", {}).items():
        unknown = [key for key in keys if key not in known_people]
        if unknown:
            raise ValueError(
                f"people_config.yaml team {team_name!r} references people not "
                f"defined under `people`: {unknown}"
            )


@functools.cache
def load_config() -> dict:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    _validate_team_members_exist(config)
    return config


def _build_people() -> dict[str, Person]:
    people = {}
    for key, attrs in load_config()["people"].items():
        human_readable = attrs.get("human_readable") or key.title().replace("_", " ")
        people[key] = Person(
            github_username=attrs["github_username"],
            slack_username=attrs["slack_username"],
            human_readable=human_readable,
        )
    return people


def team_members(team_name: str) -> list[Person]:
    """The Person instances for the named team, in defined order."""
    teams = load_config().get("teams", {})
    try:
        keys = teams[team_name]
    except KeyError:
        raise KeyError(f"Unknown team {team_name!r} in people_config.yaml") from None

    people = _build_people()
    return [people[key] for key in keys]


def by_github_username(github_username: str) -> Person:
    """The Person with this GitHub username, or a default Person built from
    it if they're not defined in people_config.yaml."""
    people = _build_people()
    for person in people.values():
        if person.github_username == github_username:
            return person
    return Person(
        human_readable=github_username,
        github_username=github_username,
        slack_username=github_username,
    )
