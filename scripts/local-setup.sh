#!/bin/bash
set -euo pipefail


FORCE_UPDATE='false'
while getopts ':f' 'OPTKEY'; do
    case ${OPTKEY} in
        'f')
            FORCE_UPDATE='true'
            ;;
        *)
            echo "Unknown option -- ${OPTARG}"
            ;;
    esac
done

BASE_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" && cd .. &> /dev/null && pwd )
ENV_FILE="$BASE_DIR/.env"
WRITEABLE_DIR="$BASE_DIR/writeable_dir"
GCP_CREDENTIALS_PATH="$WRITEABLE_DIR/gcp-credentials.json"

# ensure writeable_dir exists
mkdir -p "$WRITEABLE_DIR"

# load ensure_value function
# shellcheck disable=SC1091
. "$BASE_DIR/scripts/lib.sh"

test -f "$ENV_FILE" || cp "$BASE_DIR/dotenv-sample" "$ENV_FILE"

ensure_value LOGS_DIR "$BASE_DIR/logs" "$ENV_FILE"
ensure_value WRITEABLE_DIR "$WRITEABLE_DIR" "$ENV_FILE"
ensure_value SLACK_LOGS_CHANNEL tech-noise "$ENV_FILE"
ensure_value SLACK_TECH_SUPPORT_CHANNEL tech-support-channel "$ENV_FILE"
ensure_value SLACK_BENNETT_ADMINS_CHANNEL tech-noise "$ENV_FILE"
ensure_value SLACK_APP_USERNAME bennett_test_bot "$ENV_FILE"
ensure_value GCP_CREDENTIALS_PATH "$GCP_CREDENTIALS_PATH" "$ENV_FILE"

# shellcheck disable=SC1090
. "$ENV_FILE"

# setup secrets
# this only needs to be done very rarely, and bw client is a faff, so add a check to only do it if needed
if test -n "${CI:-}"; then
    echo "Skipping BW setup as it is CI"
elif test "$SLACK_BOT_TOKEN" = "changeme" -o -z "$SLACK_BOT_TOKEN" -o "$FORCE_UPDATE" = "true" ; then
    if ! command -v bw > /dev/null; then
        echo "bitwarden cli client bw not found"
        echo "We need it to automatically setup Bennett Bot's SLACK_BOT_TOKEN and other secrets as a one time thing"
        exit 1
    fi
    if bw status | grep -q unauthenticated; then
        echo "You are not logged in to bitwarden (org id is bennettinstitute):"
        echo
        echo "   bw login --sso"
        echo
        exit 1
    fi

    session_from_env=${BW_SESSION-"not-found"}

    if test "$session_from_env" = "not-found"; then
        echo "Unlocking bitwarden..."
        BW_SESSION=$(bw unlock --raw)
        export BW_SESSION
    fi

    # bitwarden item ids
    SLACK_BOT_TOKEN_BW_ID=2c424941-672a-4bde-847c-b1e70093aadb
    SLACK_BOT_USER_TOKEN_BW_ID=d01a1f9f-3576-4aea-94db-b1e800e5db3a
    SLACK_APP_TOKEN_BW_ID=3738619b-4e7d-4932-84b0-b1e700942908
    SLACK_SIGNING_SECRET_BW_ID=946080f1-c50f-4edf-9773-b1e70095747a
    DATA_TEAM_GITHUB_API_TOKEN_BW_ID=3c8ca5df-2fa1-49ac-afd6-b1e70092fd2a
    GCP_BW_ID=62511176-c5bd-4f9c-8de6-b1e700f570b1

    # ensure we have latest passwords
    bw sync

    # add the secrets to the env file
    ensure_value SLACK_BOT_TOKEN "$(bw get password $SLACK_BOT_TOKEN_BW_ID)" "$ENV_FILE"
    ensure_value SLACK_BOT_USER_TOKEN "$(bw get password $SLACK_BOT_USER_TOKEN_BW_ID)" "$ENV_FILE"
    ensure_value SLACK_APP_TOKEN "$(bw get password $SLACK_APP_TOKEN_BW_ID)" "$ENV_FILE"
    ensure_value SLACK_SIGNING_SECRET "$(bw get password $SLACK_SIGNING_SECRET_BW_ID)" "$ENV_FILE"
    ensure_value DATA_TEAM_GITHUB_API_TOKEN "$(bw get password $DATA_TEAM_GITHUB_API_TOKEN_BW_ID)" "$ENV_FILE"

    # create/update the GCP credentials file with the JSON retrieved from bitwarden
    echo "Writing credentials to $GCP_CREDENTIALS_PATH"
    # shellcheck disable=SC2005
    echo "$(bw get password $GCP_BW_ID)" > "$GCP_CREDENTIALS_PATH"

else
    echo "Skipping bitwarden secrets setup as it is already done. " \
         "To force an update, run this script again with the -f option."
fi
