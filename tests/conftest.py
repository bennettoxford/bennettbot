"""
Configuration for pytest.
"""

import os

import pytest

from bennettbot import settings
from workspace.utils import github_rest_api, repos_config


pytest.register_assert_rewrite("tests.assertions")


@pytest.fixture(autouse=True)
def reset_db():
    try:
        os.remove(settings.DB_PATH)
    except FileNotFoundError:
        pass


@pytest.fixture(autouse=True)
def reset_repos_config_cache():
    """Clear cached YAML config between tests so patches don't leak."""
    repos_config.load_config.cache_clear()
    yield
    repos_config.load_config.cache_clear()


@pytest.fixture(autouse=True)
def reset_github_client_cache():
    """`get_client_for_org` caches clients in a module-level dict shared by every
    caller, so clear it between tests to stop one test's cached client leaking
    into another.
    """
    github_rest_api._client_cache.clear()
    yield
    github_rest_api._client_cache.clear()


@pytest.fixture(autouse=True)
def github_app_settings():
    environ = os.environ.copy()
    os.environ["GITHUB_APP_CLIENT_ID"] = "client-id"
    os.environ["GITHUB_APP_PRIVATE_KEY"] = "private-key"
    yield
    os.environ = environ
