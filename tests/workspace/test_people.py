from workspace.utils.people import People


def test_get_person_from_github_username():
    result = People.get_person_from_github_username("lucyb")

    assert result == People.LUCY


def test_get_formatted_slack_username_from_github_username():
    result = People.get_formatted_slack_username_from_github_username("lucyb")

    assert result == "<@U035FT48KEK>"


def test_get_formatted_slack_username_from_github_username_returns_default():
    result = People.get_formatted_slack_username_from_github_username("TestUser")

    assert result == "<@TestUser>"


def test_formatted_slack_username_returns_slack_user_id():
    result = People.LUCY.formatted_slack_username

    assert result == "<@U035FT48KEK>"
