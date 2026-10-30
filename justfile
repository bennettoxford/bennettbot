import 'justfile.base'

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

# Check if a .env exists
# Use this (rather than _dotenv or devenv) for recipes that require that a .env file exists.
# just will not pick up environment variables from a .env that it's just created,
# and there isn't an easy way to load those into the environment, so we just

# prompt the user to run just devenv to set up their local environment properly.
_checkenv:
    #!/usr/bin/env bash
    set -euo pipefail

    if [[ ! -f .env ]]; then
        echo "No '.env' file found; run 'just devenv' to create one"
        exit 1
    fi

    target="${WRITEABLE_DIR}/repos_config.yaml"
    if [[ ! -f "$target" ]]; then
      config_example="repos_config.sample.yaml"
      echo "No 'repos_config.yaml' found in WRITEABLE_DIR; copying from $config_example"
      mkdir -p "$WRITEABLE_DIR"
      cp "$config_example" "$target"
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
devenv: _dotenv && install-precommit
    uv sync --inexact

# Ensure precommit is installed
install-precommit:
    #!/usr/bin/env bash
    set -euo pipefail

    BASE_DIR=$(git rev-parse --show-toplevel)
    test -f $BASE_DIR/.git/hooks/pre-commit || uv run pre-commit install

# recipe is only used if we want upgrade packages outside of dependabot
upgrade-package package cooldown="7 days ago": && devenv
    uv lock --upgrade-package {{ package }}

# The upgrade-all recipe is used for doing lockfileMaintenance via update-dependencies action, until min release age is respected fo uv
# Note that we run devenv with && to remove the timestamp written into the uv.lock file

# upgrade all dependencies with specified cooldown
upgrade-all cooldown="7 days ago": && devenv
    uv lock --upgrade --exclude-newer "{{ cooldown }}"

# update the companion requirements formatted file
uvmirror file="requirements.uvmirror":
    rm -f {{ file }}
    uv export --format requirements-txt --frozen --no-hashes --all-groups --all-extras > {{ file }}

update-dependencies: upgrade-all && uvmirror

# *ARGS is variadic, 0 or more. This allows us to do `just test -k match`, for example.

# Run the tests
test *ARGS:
    uv run coverage run --module pytest {{ ARGS }}
    uv run coverage report || $BIN/coverage html

format *args:
    uv run ruff format --diff --quiet {{ args }} .

lint *args:
    uv run ruff check {{ args }} .

shellcheck:
    {{ docker_run_safe }} -v "$PWD:/mnt:ro" koalaman/shellcheck:{{ shellcheck_version }} scripts/*

lint-actions:
    {{ docker_run_safe }} -v $(pwd):/repo:ro --workdir /repo kjanat/actionlint:{{ actionlint_version }} -color

# Run the various dev checks but does not change any files
check:
    #!/usr/bin/env bash
    set -euo pipefail

    failed=0

    check() {
      echo -e "\e[1m=> ${1}\e[0m"
      rc=0
      # Run it
      eval $1 || rc=$?
      # Increment the counter on failure
      if [[ $rc != 0 ]]; then
        failed=$((failed + 1))
        # Add spacing to separate the error output from the next check
        echo -e "\n"
      fi
    }

    check "just format"
    check "just lint"
    check "just lint-actions"
    check "just shellcheck"
    test -d docker/ && check "just docker/lint"

    if [[ $failed > 0 ]]; then
      echo -en "\e[1;31m"
      echo "   $failed checks failed"
      echo -e "\e[0m"
      exit 1
    fi

# Fix formatting and import sort ordering
fix:
    uv run ruff check --fix .
    uv run ruff format .
    just --fmt --unstable
    just --fmt --unstable --justfile docker/justfile

# Run the dev project
run SERVICE: _checkenv
    uv run python -m bennettbot.{{ SERVICE }}

check-renovate-config:
    {{ docker_run_safe }} -v $(pwd):/repo:ro --workdir /repo renovate/renovate:{{ renovate_version }} renovate-config-validator

# Show what updates Renovate would propose.
# summary: table with version age and pending status
# packages: structured JSON of proposed package updates

# full: complete Renovate debug log
renovate-dry-run output="summary":
    #!/usr/bin/env bash
    set -euo pipefail

    echo "Running Renovate, this may take a few minutes" >&2

    # Buffer Renovate's output so progress dots can't appear in the middle of the formatted JSON or summary table.
    log_file=$(mktemp)
    progress_pid=""

    cleanup() {
        if [[ -n "$progress_pid" ]]; then
            kill "$progress_pid" 2>/dev/null || true
            wait "$progress_pid" 2>/dev/null || true
            progress_pid=""
        fi
        rm -f "$log_file"
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    run_renovate() {
        # We can't use docker_run_safe because --network none prevents
        # Renovate querying Docker, GitHub, PyPI, etc.
        #
        # Renovate also needs writable working/cache directories.
        # Give it a tmpfs mount and leave everything else read-only.

        # Let the user know something is still happening.
        (
            while sleep 5; do
                printf '.' >&2
            done
        ) &
        progress_pid=$!

        local status=0

        docker run --rm --read-only --tmpfs /tmp \
            --cap-drop ALL \
            --security-opt no-new-privileges:true \
            --user 65534:65534 \
            -e HOME=/tmp \
            -v "$(pwd):/repo:ro" \
            --workdir /repo \
            -e LOG_LEVEL=debug \
            -e LOG_FORMAT=json \
            renovate/renovate:{{ renovate_version }} \
            --platform=local > "$log_file" || status=$?

        # Stop the progress indicator before printing any output.
        kill "$progress_pid" 2>/dev/null || true
        wait "$progress_pid" 2>/dev/null || true
        progress_pid=""
        echo >&2

        return "$status"
    }

    # Run Renovate once, then format the buffered output.
    if ! run_renovate; then
        echo "Renovate failed. Last 30 log lines:" >&2
        tail -n 30 "$log_file" >&2
        exit 1
    fi

    case "{{ output }}" in
        summary)
            jq -rRn '
                # Truncate to the first 19 characters.
                # Keep the full version number.
                def format_digest:
                    if . then
                        "@" + .[:19] + "..."
                    else
                        ""
                    end;

                ["PACKAGE", "CURRENT", "NEW", "AGE", "STATUS"],
                (
                    inputs
                    | fromjson?
                    | objects
                    | select(.msg == "packageFiles with updates")
                    | .config[][]
                    | .deps[]
                    | .depName as $name
                    | (
                        (.currentValue // .currentVersion // "-")
                        + (.currentDigest | format_digest)
                      ) as $current
                    | (.updates // [])[]
                    | [
                        $name,
                        $current,
                        (
                            (.newValue // .newVersion // "-")
                            + (.newDigest | format_digest)
                        ),
                        (
                            if .newVersionAgeInDays != null then
                                "\(.newVersionAgeInDays)d"
                            else
                                "-"
                            end
                        ),
                        (
                            if .pendingChecks then
                                "pending"
                            else
                                "ready"
                            end
                        )
                    ]
                )
                | @tsv
            ' "$log_file" | column -t -s $'\t'
            ;;

        packages)
            jq -R '
                fromjson?
                | objects
                | select(.msg == "packageFiles with updates")
                | .config
            ' "$log_file"
            ;;

        full)
            jq -R 'fromjson? // .' "$log_file"
            ;;

        *)
            echo "Unknown output '{{ output }}': use 'summary', 'packages' or 'full'" >&2
            exit 1
            ;;
    esac

# Run a full Renovate dry run against this branch (requires pushing the branch first)
renovate-dry-run-github branch:
    # This checks some things that renovate-dry-run (which runs against local files)
    # can't, e.g. lockFileMaintenance, which depend on it determinining what branches
    # and PRs it would need to make.
    # Note that we can't use docker_run_safe here because `--network none` stops
    # Renovate querying docker, github, pypi etc for updates. It's not --read-only
    # because it needs to install uv and npm; however, it doesn't need to mount in
    # any local files because it's pulling a remote branch.
    docker run --rm --tmpfs /tmp \
        --cap-drop ALL --security-opt no-new-privileges:true \
        -e LOG_LEVEL=debug -e LOG_FORMAT=json \
        -e RENOVATE_TOKEN="$(gh auth token)" \
        renovate/renovate:{{ renovate_version }} \
        --platform=github --dry-run=full \
        --base-branch-patterns={{ branch }} --use-base-branch-config=merge \
        opensafely-core/pipeline
