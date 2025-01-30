from collections import namedtuple
from enum import Enum


_person = namedtuple("_person", ["github_username", "slack_username"])


class People(Enum):
    """Tech team members' GitHub and Slack usernames."""

    # Find a Slack user's username by right-clicking on their name in the Slack app and clicking "Copy link".

    ALICE = _person("alarthast", "U07KX6L3CMA")
    BECKY = _person("rebkwok", "U01SP5JLBFD")
    BEN_BC = _person("benbc", "U01SPCP06Q1")
    CATHERINE = _person("CLStables", "U036A6LTR7D")
    DAVE = _person("evansd", "UAXE5V4RG")
    ELI = _person("eli-miriam", "U07LHEJ9TS4")
    IAIN = _person("iaindillingham", "U01S6BLGK28")
    JON = _person("Jongmassey", "U023ZG5H24R")
    KATIE = _person("KatieB5", "U07KUKWBGKV")
    LUCY = _person("lucyb", "U035FT48KEK")
    MARY = _person("Mary-Anya", "U07LKQ06Q8L")
    MILAN = _person("milanwiedemann", "U02GPV8NNU9")
    MIKE = _person("mikerkelly", "U07KKL4PJJY")
    PETER = _person("inglesp", "U4N1YPAP7")
    PROVIDENCE = _person("Providence-o", "U07AGDM6ZJN")
    RICHARD = _person("rw251", "U07QEMHUUMD")
    SIMON = _person("bloodearnest", "U01AMBZUT47")
    STEVE = _person("StevenMaude", "U01TJP3CG76")
    THOMAS = _person("tomodwyer", "U01UQ0T2M7V")
    TOM_P = _person("remlapmot", "U07L0L0SS6M")
    TOM_W = _person("madwort", "U019R5FJ7G8")

    @property
    def human_readable(self):
        return self.name.title().replace("_", " ")

    @property
    def formatted_slack_username(self):
        return self.__class__._slack_format(self.value.slack_username)

    @property
    def github_username(self):
        return self.value.github_username

    @staticmethod
    def _slack_format(username):
        return f"<@{username}>"

    @classmethod
    def get_person_from_github_username(cls, github_username):
        return {person.github_username: person for person in cls}.get(
            github_username, None
        )

    @classmethod
    def get_formatted_slack_username_from_github_username(cls, github_username):
        person = cls.get_person_from_github_username(github_username)
        if person:
            return person.formatted_slack_username
        else:
            return cls._slack_format(github_username)


TEAM_REX = [
    People.JON,
    People.KATIE,
    People.LUCY,
    People.STEVE,
    People.MIKE,
    People.THOMAS,
]
