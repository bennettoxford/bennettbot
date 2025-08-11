from dataclasses import dataclass
from typing import Optional


@dataclass(order=True)
class Person:
    github_username: str
    slack_username: str
    # Optional because this is mostly set in PersonCollection.__init__().
    human_readable: Optional[str] = ""

    @property
    def formatted_slack_username(self) -> str:
        return f"<@{self.slack_username}>"


class PersonCollection(type):
    """Metaclass for collections of Person instances."""

    def __init__(cls, name, bases, namespace):
        # dict mapping github_username to People instances, for later lookups.
        cls._by_github_username = {}

        people_items = [
            item for item in namespace.items() if isinstance(item[1], Person)
        ]
        for attribute_name, person in people_items:
            cls._by_github_username[person.github_username] = person
            # Populate human_readable based on attribute value if not set explicitly.
            if not person.human_readable:
                person.human_readable = attribute_name.title().replace("_", " ")

        super().__init__(name, bases, namespace)

    def __iter__(cls):
        # Enable iteration by `for person in People` or similar to work.
        return iter(
            sorted(value for value in vars(cls).values() if isinstance(value, Person))
        )


class People(metaclass=PersonCollection):
    """Tech team members' GitHub and Slack usernames."""

    # Find a Slack user's username by right-clicking on their name in the Slack
    # app and clicking "Copy link".

    # human_readable is mostly set by PersonCollection.__init__() but can be
    # overriden as the third argument if required. This avoids the need to
    # explicitly specify it for most people.
    ALICE = Person("alarthast", "U07KX6L3CMA")
    BECKY = Person("rebkwok", "U01SP5JLBFD")
    BEN_BC = Person("benbc", "U01SPCP06Q1", "Ben BC")
    CATHERINE = Person("CLStables", "U036A6LTR7D")
    DAVE = Person("evansd", "UAXE5V4RG")
    ELI = Person("eli-miriam", "U07LHEJ9TS4")
    IAIN = Person("iaindillingham", "U01S6BLGK28")
    JON = Person("Jongmassey", "U023ZG5H24R")
    KATIE = Person("KatieB5", "U07KUKWBGKV")
    KLAUDIA = Person("klau-b", "U07CBHR2QBF")
    LUCY = Person("lucyb", "U035FT48KEK")
    LINDA = Person("L1-r0y", "U07LEDB8XEZ")
    MARY = Person("Mary-Anya", "U07LKQ06Q8L")
    MILAN = Person("milanwiedemann", "U02GPV8NNU9")
    MIKE = Person("mikerkelly", "U07KKL4PJJY")
    NISHTHA = Person("nishtha-kalra", "U09863KPURF")
    PETER = Person("inglesp", "U4N1YPAP7")
    PROVIDENCE = Person("Providence-o", "U07AGDM6ZJN")
    RICHARD = Person("rw251", "U07QEMHUUMD")
    SEB = Person("sebbacon", "U321M2RMZ")
    SIMON = Person("bloodearnest", "U01AMBZUT47")
    STEVE = Person("StevenMaude", "U01TJP3CG76")
    THOMAS = Person("tomodwyer", "U01UQ0T2M7V")
    TOM_P = Person("remlapmot", "U07L0L0SS6M")
    TOM_W = Person("madwort", "U019R5FJ7G8")

    @classmethod
    def by_github_username(cls, github_username):
        default = Person(
            human_readable=github_username,
            github_username=github_username,
            slack_username=github_username,
        )
        return cls._by_github_username.get(github_username, default)


# Note that adding to or re-ordering this list will will affect the
# DependabotRotaReporter ordering algorithm, restarting it at an arbitrary
# point. If you need to change this list, consider redesigning that class to
# include an offset.
TEAM_REX = [
    People.JON,
    People.KATIE,
    People.LUCY,
    People.STEVE,
    People.MIKE,
    People.THOMAS,
]
