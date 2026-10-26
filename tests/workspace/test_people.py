import pytest

from workspace.utils import people


def test_by_github_username():
    result = people.by_github_username("person-one")

    assert result == people.team_members("Team REX")[0]


def test_by_github_username_returns_default_for_unknown_user():
    result = people.by_github_username("someone-unknown")

    assert result.human_readable == "someone-unknown"
    assert result.github_username == "someone-unknown"
    assert result.slack_username == "someone-unknown"


def test_formatted_slack_username():
    person = people.by_github_username("person-one")

    assert person.formatted_slack_username == "<@UPERSONONE1>"


def test_human_readable_defaults_to_title_cased_key():
    person = people.by_github_username("person-one")

    assert person.human_readable == "Person One"


def test_human_readable_can_be_overridden():
    person = people.by_github_username("test-person")

    assert person.human_readable == "Overridden Name"


def test_team_members_returns_people_in_order():
    assert people.team_members("Team REX") == [
        people.by_github_username("person-one"),
        people.by_github_username("person-two"),
        people.by_github_username("person-three"),
    ]


def test_team_members_raises_for_unknown_team():
    with pytest.raises(KeyError):
        people.team_members("Team Nonexistent")


def test_load_config_raises_for_team_member_not_defined_under_people(
    tmp_path, monkeypatch
):
    bad_config = tmp_path / "people_config.yaml"
    bad_config.write_text(
        "people:\n"
        "  PERSON_ONE:\n"
        "    github_username: person-one\n"
        "    slack_username: UPERSONONE1\n"
        "teams:\n"
        "  Team Testing:\n"
        "    - PERSON_ONE\n"
        "    - GHOST\n"
    )
    monkeypatch.setattr(people, "CONFIG_PATH", bad_config)

    with pytest.raises(ValueError, match="GHOST"):
        people.load_config()
