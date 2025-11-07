# Notes for developers

## System requirements

### just

Follow installation instructions from the [Just Programmer's Manual](https://just.systems/man/en/packages.html "Follow installation instructions for your OS").

#### Add completion for your shell. E.g. for bash:
```
source <(just --completions bash)
```

#### Show all available commands
```
just #  shortcut for just --list
```

### shellcheck
```sh
# macOS
brew install shellcheck

# Linux
sudo apt install shellcheck
```


### uv

Follow installation instructions from the [uv documentation](https://docs.astral.sh/uv/getting-started/installation/) for your OS.


## Dependency management
Dependencies are managed with `uv`.

### Overview
See the [uv documentation](https://docs.astral.sh/uv/concepts/projects/dependencies) for details on usage.
Commands for adding, removing or modifying constraints of dependencies will automatically respect the
global timestamp cutoff specified in the `pyproject.toml`:
```toml
[tool.uv]
exclude-newer = "YYYY-MM-DDTHH:MM:SSZ"
```
Changes to dependencies should be made via `uv` commands, or by modifying `pyproject.toml` directly followed by
[locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) via `uv` or `just` commands like
`just devenv` or `just upgrade-all`. You should not modify `uv.lock` manually.

Note that `uv.lock` must be reproducible from `pyproject.toml`. Otherwise, `just check` will fail.
If `just check` errors saying that the timestamps must match, you might have modified one file but not the other:
  - If you modified `pyproject.toml`, you must update `uv.lock` via `uv lock` / `just upgrade-all` or similar.
  - If you did not modify `pyproject.toml` but have changes in `uv.lock`, you should revert the changes to `uv.lock`,
  modify `pyproject.toml` as you require, then run `uv lock` to update `uv.lock`.

The timestamp cutoff should usually be set to midnight UTC of a past date.
In general, the date is expected to be between 7 and 14 days ago as a result of automated weekly dependency updates.

If you require a package version that is newer than the cutoff allows, you can either manually bump the global cutoff
date or add a package-specific timestamp cutoff. Both options are described below.

### Manually bumping the cutoff date
The cutoff timestamp can be modified to a more recent date either manually in the `pyproject.toml`
or with `just bump-uv-cutoff <days-ago>`.
For example, to set the cutoff to today's date and upgrade all dependencies, run:
```
just bump-uv-cutoff 0
just upgrade-all
```

### Adding a package-specific timestamp cutoff
It is possible to specify a package-specific timestamp cutoff in addition to the global cutoff.
This should be done in the `pyproject.toml` to ensure reproducible installs;
see the [uv documentation](https://docs.astral.sh/uv/reference/settings/#exclude-newer-package) for details.
If set, the package-specific cutoff will take precedence over the global cutoff regardless of which one is more recent.

You should not set a package-specific cutoff that is older than the global cutoff - use a version
constraint instead.
If there is good reason to set a package-specific cutoff that is more recent than the global cutoff,
**care should be taken to ensure that the package-specific cutoff is manually removed once it is over 7 days old**,
as otherwise future automated updates of that package will be indefinitely blocked.
Currently no automated tooling is in place to enforce removal of stale package-specific cutoffs.


## Local development environment

Set up a local development environment with:
```
just devenv
```

### .env file

Set up your local .env file by running

```
./scripts/local-setup.sh
```

This will create a `.env` file by copying `dotenv-sample`, and will use the
Bitwarden CLI to retrieve relevant dev secrets and update environment variables and credentials.

By default, re-running the script will skip updating secrets from Bitwarden
if they are already populated. To force them to update again:

```
./scripts/local-setup.sh -f
```

### bitwarden CLI

If you don't have the Bitwarden CLI already installed, the `local-setup.sh`
will prompt you to [install it](https://bitwarden.com/help/cli/#download-and-install).


### Join the test slack workspace

Join the test Slack workspace at [bennetttest.slack.com](https://bennetttest.slack.com).

The test slack bot's is already installed to this workspace.  Its username is
`bennett_test_bot` and, when you are running the bot locally, you can
interact with it by using `@Bennett Test Bot`.

Alternatively, you can [create your own new slack workspace](https://slack.com/get-started#/createnew) to use for testing, and follow the instructions in the [deployment docs](DEPLOY.md) to create a new test slack app, generate tokens
and install it to the workspace. You will need to update your `.env` file with
the relevant environment variables.

## Run locally

### Run checks

Run linter, formatter and shellcheck:
```
just check
```

Fix issues:
```
just fix
```

### Tests
Run the tests with:
```
just test <args>
```

### Run individual services:
```
just run <service>
```

To run the slack bot and use it to run jobs, run both the bot and dispatcher:
```
just run bot
just run dispatcher
```

## Run in docker

### Build docker image

This builds the dev image by default:

```
just docker/build
```

### Run checks

```
just docker/check`
```

### Run tests
```
just docker/test
```

### Run all services

Run all 3 services (bot, dispatcher and webserver) in separate docker
containers.

```
just docker/run-all
```

### Restart all services

Restart all running services.

```
just docker/restart
```

### Stop/remove containers

Stop running service container:

```
just docker/stop-all
```

Stop running services and remove containers:

```
just docker/rm-all
```
