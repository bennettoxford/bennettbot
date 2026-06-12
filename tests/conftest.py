"""
Configuration for pytest.
"""

import os

import pytest

from bennettbot import settings
from workspace.utils import repos_config


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
