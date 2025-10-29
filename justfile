set dotenv-load := true


# list available commands
default:
    @"{{ just_executable() }}" --list


# Create a valid .env if none exists
_dotenv:
    #!/usr/bin/env bash
    set -euo pipefail

    if [[ ! -f .env ]]; then
      echo "No '.env' file found; creating a default '.env' from 'dotenv-sample'"
      cp dotenv-sample .env
    fi


# clean up temporary files
clean:
    rm -rf .venv


# Install production requirements into and remove extraneous packages from venv
prodenv:
    uv sync --no-dev


# && dependencies are run after the recipe has run. Needs just>=0.9.9. This is
# a killer feature over Makefiles.
#
# Install dev requirements into venv without removing extraneous packages
devenv: && install-precommit
    uv sync --inexact


# Ensure precommit is installed
install-precommit:
    #!/usr/bin/env bash
    set -euo pipefail

    BASE_DIR=$(git rev-parse --show-toplevel)
    test -f $BASE_DIR/.git/hooks/pre-commit || uv run pre-commit install


# Upgrade a single package to the latest version as of the cutoff in pyproject.toml
upgrade-package package: && devenv
    uv lock --upgrade-package {{ package }}


# Upgrade all packages to the latest versions as of the cutoff in pyproject.toml
upgrade-all: && devenv
    uv lock --upgrade


# Move the cutoff date in pyproject.toml to N days ago (default: 7) at midnight UTC
bump-uv-cutoff days="7":
    #!/usr/bin/env -S uvx --with tomlkit python3

    import datetime
    import tomlkit

    with open("pyproject.toml", "rb") as f:
        content = tomlkit.load(f)

    new_datetime = (
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=int("{{ days }}"))
    ).replace(hour=0, minute=0, second=0, microsecond=0)
    new_timestamp = new_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
    if existing_timestamp := content["tool"]["uv"].get("exclude-newer"):
        if new_datetime < datetime.datetime.fromisoformat(existing_timestamp):
            print(
                f"Existing cutoff {existing_timestamp} is more recent than {new_timestamp}, not updating."
            )
            exit(0)
    content["tool"]["uv"]["exclude-newer"] = new_timestamp

    with open("pyproject.toml", "w") as f:
        tomlkit.dump(content, f)


# This is the default input command to update-dependencies action
# https://github.com/bennettoxford/update-dependencies-action
# Bump the timestamp cutoff to midnight UTC 7 days ago and upgrade all dependencies
update-dependencies: bump-uv-cutoff upgrade-all


# *ARGS is variadic, 0 or more. This allows us to do `just test -k match`, for example.
# Run the tests
test *ARGS:
    uv run coverage run --module pytest {{ ARGS }}
    uv run coverage report || $BIN/coverage html


format *args="--diff --quiet .":
    uv run ruff format --check {{ args }}


lint *args="--output-format=full .":
    uv run ruff check {{ args }}

shellcheck:
    shellcheck scripts/*

# Runs the various dev checks but does not change any files
check: && format lint shellcheck # Check the lockfile before `uv run` is used
    #!/usr/bin/env bash
    set -euo pipefail

    # Make sure dates in pyproject.toml and uv.lock are in sync
    unset UV_EXCLUDE_NEWER
    rc=0
    uv lock --check || rc=$?
    if test "$rc" != "0" ; then
        echo "Timestamp cutoffs in uv.lock must match those in pyproject.toml. See DEVELOPERS.md for details and hints." >&2
        exit $rc
    fi


# Fix formatting and import sort ordering
fix:
    uv run ruff check --fix .
    uv run ruff format .


# Run the dev project
run SERVICE: devenv
    uv run python -m bennettbot.{{ SERVICE }}
