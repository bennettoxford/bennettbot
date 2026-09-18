## Deployment

Deployment uses `dokku` and requires the environment variables defined
[below](#configure-app-environment-variables).

It is deployed to our `dokku3` instance [automatically via GitHub actions](#deployment-via-github-actions).


It runs as a single dokku app named `bennettbot`, with multiple processes for each
service (bot, dispatcher and webserver) as defined in the `Procfile`.

## Creating the Slack app
(This should only need to be done once).

bennettbot needs a new-style Slack app and uses
[socket mode](https://slack.dev/bolt-python/concepts#socket-mode) to listen for messages.
To create one:

### Create the app
1. visit <https://api.slack.com/apps>
2. Click the "Create new app" button and choose the "From scratch" option
3. Name the app and select the Bennett Institute workspace to develop it in.
   After creating the app, you'll be dropped into the app's page.

### Enable socket mode and create app token
1. Settings > Socket Mode
2. Enable Socket Mode; this will create the app token.  Give the token a name and accept
   the default scope assigned (`connections:write`).
3. Go to Settings > Basic information, and under App Level Tokens you'll now see the token
   you just created.  This token starts `xapp-` and should be the value set for the
   `SLACK_APP_TOKEN` environment variable

### Add event subscriptions
Add event subscriptions to allow the app to be notified of events in Slack/
1. Features > Event subscriptions; toggle on
2. In Subscribe to bot events, add the following events:
   - message.channels
   - message.groups
   - message.im
   - message.mpim
   - channel_created
   - app_mention
3. Save changes

### Add Bot scopes
Adding the event subscriptions above automatically adds the required oauth scopes for the
events.  We need to add some more:
1. Features > OAuth & Permissions: scroll down to Scopes
   You should see the following Bot Token Scopes already assigned:
   - `channels:history`
   - `groups:history`
   - `im:history`
   - `mpim:history`
   - `channels:read`
   - `app_mentions:read`
2. Add the following additional scopes:
   - `channels:join`
   - `users:read`
   - `groups:read`
   - `mpim:read`
   - `im:read`
   - `reactions:write`
   - `chat:write`
   - `files:write`

### Add User scopes
We need a User token for the app in order to search slack messages:
1. Features > OAuth & Permissions: scroll down to Scopes. User Token Scopes
   are found after the Bot Token Scopes. By default the app has no user scopes.
2. Add the following scopes:
   - `search:read`

### Allow users to DM the app
1. Features > App Home
2. Under Messages Tabs, ensure the "Allow users to send Slash commands and messages from
  the messages tab" is ticked.

### Install the app
1. Features > OAuth & Permissions
2. Under "OAuth Tokens for Your Workspace", click "Install to Workspace"
3. This will generate the bot token (starts `xoxb-`) and the user token (starts `xoxp-`)

If you update any scopes after installing the app, you'll need to reinstall it (slack will
usually prompt for this).

## Configuring the dokku app
(This should only need to be done once).

### Create app

```sh
$ dokku apps:create bennettbot
```

### Create storage for sqlite db, logs and fabric job workspaces
```sh
$ mkdir -p /var/lib/dokku/data/storage/bennettbot/logs
$ mkdir -p /var/lib/dokku/data/storage/bennettbot/workspace
$ dokku storage:mount bennettbot /var/lib/dokku/data/storage/bennettbot/:/storage
```

### Set up the user

This is done using the ansible playbook in `https://github.com/ebmdatalab/sysadmin/blob/main/infra`.

See <https://github.com/ebmdatalab/sysadmin/blob/main/infra/README.md> for more details.

To run just the bennettbot tasks:

```sh
just test dokku3 --tags bennettbot
```
And if all looks OK:

```sh
just apply dokku3 --tags bennettbot
```

This will create the bennettbot user on dokku3 and chown any mounted volumes.


### Create ssh key and mount bennettbot user's home directory

Create an ssh key for the bennettbot user, in the usual $HOME/.ssh/ location.

Mount the user's home directory into the app.

```sh
$ dokku storage:mount bennettbot /home/bennettbot/:/home/bennettbot
```

Add the bennettbot user's key to any servers that it requires access to
(i.e. any jobs that run `fab` commands).

### Configure GitHub app

Calls to the GitHub API require a GitHub App, installed on each of our organisations.

Using a GitHub App means that we make calls to the GitHub API using short-lived
installation tokens that only have the specific permissions each call requires, and
are not linked to any individual developer's account.

#### Create the app

If no app exists yet, follow the docs to [register an app to an organisation](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app).

It does not require any special options, callbacks or webhook URL.

#### Set permissions

Add the following permissions:
- Repo:
    - Actions (read only)
    - Codespaces (read only)
    - Dependabot alerts (read only)
- Org:
    - Organization codespaces (read only)
    - Projects (read only)

#### Generate a private key
Generate a private key and save the pem file.

#### Install the app and get installation IDs
Make the app public.

Install the app into each org and find the installation ID for each (go to the org settings > third party apps, click on the app and look for the ID in the URL
`https://github.com/organizations/<org>/settings/installations/<installation_id>`


### Configure app environment variables

See also comments in `bennettbot/settings.py`.

The following slack environment variables need to be set:
- `SLACK_LOGS_CHANNEL`: channel where scheduled job notifications will be posted
- `SLACK_BENNETT_ADMINS_CHANNEL`: channel where bennett-admins requests will be reposted
- `SLACK_TECH_SUPPORT_CHANNEL`: channel where tech-support requests will be reposted
- `SLACK_APP_TOKEN`: app-level token generated above (starts `xapp-`); found on the app's Basic Information page
- `SLACK_BOT_TOKEN`: bot token generated above (starts `xoxb-`); found on the app's Oauth and Permissions page
- `SLACK_BOT_USER_TOKEN`: user token generated above (starts `xoxp-`); found on the app's Oauth and Permissions page
- `SLACK_SIGNING_SECRET`: Found on the app's Basic Information page, under App Credentials
- `SLACK_APP_USERNAME`: The app's default name (and the name users will refer to the Bot as in Slack); found under Features > App Home

The following webhook environment variables need to be set. These relate to callbacks from
OpenPrescribing, and are configured at https://github.com/bennettoxford/openprescribing/settings/hooks/85994427.
- `GITHUB_WEBHOOK_SECRET`
- `WEBHOOK_ORIGIN`

GitHub App credentials:
- `GITHUB_APP_CLIENT_ID`: set this to the App Client ID, found on the GitHub App page
- `GITHUB_APP_PRIVATE_KEY`: set this the the private key generated for the app (the contents of the pem file)

This is the path to credentials for the gdrive@ebmdatalab.iam.gserviceaccount.com
service account:
- `GCP_CREDENTIALS_PATH`

The path for logs; set this to a directory in the dokku mounted storage so the logs
persist outside of the containers.
- `LOGS_DIR`
Also set the alias for the logs dir to the location of the mounted volume on the host,
for error reporting
- `HOST_LOGS_DIR`

The path for the sqlite db file; set this to a file in the dokku mounted storage
- `DB_PATH`

A path to a directory that jobs can write files to. Set this to a directory in the
dokku mounted storage that the docker user will have write access to.
- `WRITEABLE_DIR`

Path for file created after bot startup (used in the bot healthcheck in `app.json`).
- `BOT_CHECK_FILE`

Set each env varible with:
```sh
$ dokku config:set bennettbot ENVVAR_NAME=value
```

e.g.
```sh
$ dokku config:set bennettbot LOGS_DIR=/storage/logs
$ dokku config:set bennettbot HOST_LOGS_DIR=/var/lib/dokku/data/storage/bennettbot/logs
$ dokku config:set bennettbot DB_PATH=/storage/bennettbot.db
$ dokku config:set bennettbot FAB_WORKSPACE_DIR=/storage/workspace
$ dokku config:set bennettbot BOT_CHECK_FILE=/storage/.bot_startup_check
```

### Add the repo_config

Make a copy of <repos_config.sample.yaml>, and save it to the mounted $WRITEABLE_DIR (i.e.
if WRITEABLE_DIR is mounted from `/var/lib/dokku/data/storage/bennettbot/` on the host,
put this file at `/var/lib/dokku/data/storage/bennettbot/repos_config.yaml`.

Update the repo_config.yaml to add the [installation IDs for each organisation](#install-the-app-and-get-installation-ids).


### Map port 9999 for incoming github hooks
https://dokku.com/docs/networking/port-management/

dokku ports:add bennettbot http:9999:9999


## Deployment via GitHub Actions

Merges to the `main` branch will trigger an auto-deploy via GitHub actions.

Note this deploys by building the prod docker image (see `docker/docker-compose.yaml`) and using the dokku [git:from-image](https://dokku.com/docs/deployment/methods/git/#initializing-an-app-repository-from-a-docker-image) command.


### Manually deploying

To deploy manually:

```
# build prod image locally
just docker/build prod

# tag image and push
docker tag bennettbot ghcr.io/bennettoxford/bennettbot:latest
docker push ghcr.io/bennettoxford/bennettbot:latest

# get the digest for the latest image
IMAGE_DIGEST=$(docker inspect --format='{{join .RepoDigests "\n"}}' ghcr.io/bennettoxford/bennettbot:latest | grep -F 'ghcr.io/')
```

On dokku3:
```
$ dokku git:from-image bennettbot <IMAGE_DIGEST>
```
