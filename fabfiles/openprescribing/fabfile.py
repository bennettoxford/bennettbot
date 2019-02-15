from __future__ import print_function
from fabric.api import run, sudo
from fabric.api import prefix, warn, abort
from fabric.api import settings, task, env, shell_env
from fabric.context_managers import cd
from fabric.contrib.files import exists

from datetime import datetime
import json
import os

import dotenv
import requests

basedir = os.path.dirname(os.path.abspath(__file__))
dotenv.read_dotenv(os.path.join(basedir, 'environment'))


env.hosts = ['web2.openprescribing.net']
env.forward_agent = True
env.colorize_errors = True
env.user = 'hello'

environments = {
    'production': 'openprescribing',
    'staging': 'openprescribing_staging'
}

# This zone ID may change if/when our account changes
# Run `fab list_cloudflare_zones` to get a full list
ZONE_ID = "198bb61a3679d0e1545e838a8f0c25b9"

# Newrelic Apps
NEWRELIC_APPIDS = {
    'production': '45170403',
    'staging': '45937313',
    'test': '45170011'
}


def sudo_script(script, www_user=False):
    """Run script under `deploy/fab_scripts/` as sudo.

    We don't use the `fabric` `sudo()` command, because instead we
    expect the user that is running fabric to have passwordless sudo
    access.  In this configuration, that is achieved by the user being
    a member of the `fabric` group (see `setup_sudo()`, below).

    """
    if www_user:
        sudo_cmd = 'sudo -u www-data '
    else:
        sudo_cmd = 'sudo '
    return run(sudo_cmd +
               os.path.join(
                   env.path,
                   'deploy/fab_scripts/%s' % script))


def setup_sudo():
    """Ensures members of `fabric` group can execute deployment scripts as
    root without passwords

    """
    sudoer_file_test = '/tmp/openprescribing_fabric_{}'.format(
        env.app)
    sudoer_file_real = '/etc/sudoers.d/openprescribing_fabric_{}'.format(
        env.app)
    # Raise an exception if not set up
    check_setup = run(
        "/usr/bin/sudo -n {}/deploy/fab_scripts/test.sh".format(env.path),
        warn_only=True)
    if check_setup.failed:
        # Test the format of the file, to prevent locked-out-disasters
        run(
            'echo "%fabric ALL = (root) '
            'NOPASSWD: {}/deploy/fab_scripts/" > {}'.format(
                env.path, sudoer_file_test))
        run('/usr/sbin/visudo -cf {}'.format(sudoer_file_test))
        # Copy it to the right place
        sudo('cp {} {}'.format(sudoer_file_test, sudoer_file_real))


def notify_slack(message):
    """Posts the message to #general
    """
    # Set the webhook_url to the one provided by Slack when you create
    # the webhook at
    # https://my.slack.com/services/new/incoming-webhook/
    webhook_url = os.environ['SLACK_GENERAL_POST_KEY']
    slack_data = {'text': message}

    response = requests.post(webhook_url, json=slack_data)
    if response.status_code != 200:
        raise ValueError(
            'Request to slack returned an error %s, the response is:\n%s'
            % (response.status_code, response.text)
        )


def notify_newrelic(revision, url):
    payload = {
        "deployment": {
            "revision": revision,
            "changelog": url
        }
    }
    app_id = NEWRELIC_APPIDS[env.environment]
    headers = {'X-Api-Key': os.environ['NEWRELIC_API_KEY']}
    response = requests.post(
        ("https://api.newrelic.com/v2/applications/"
         "%s/deployments.json" % app_id),
        headers=headers,
        json=payload)
    response.raise_for_status()


def git_init():
    run('git init . && '
        'git remote add origin '
        'https://github.com/ebmdatalab/openprescribing.git && '
        'git fetch origin && '
        'git branch --set-upstream master origin/master')


def venv_init():
    run('virtualenv .venv')


def git_pull():
    run('git fetch --all')
    run('git checkout --force origin/%s' % env.branch)


def pip_install():
    if 'requirements.txt' in env.changed_files:
        with prefix('source .venv/bin/activate'):
            run('pip install -r requirements.txt')


def npm_install():
    installed = run("if [[ -n $(which npm) ]]; then echo 1; fi")
    if not installed:
        sudo('curl -sL https://deb.nodesource.com/setup_6.x |'
             'bash - && apt-get install -y  '
             'nodejs binutils libproj-dev gdal-bin libgeoip1 libgeos-c1;',
             user=env.local_user)
        sudo('npm install -g browserify && npm install -g eslint',
             user=env.local_user)


def npm_install_deps(force=False):
    if force or 'openprescribing/media/js/package.json' in env.changed_files:
        run('cd openprescribing/media/js && npm install')


def npm_build_js():
    run('cd openprescribing/media/js && npm run build')


def npm_build_css(force=False):
    if force or filter(lambda x: x.startswith('openprescribing/media/css'),
                       [x for x in env.changed_files]):
        run('cd openprescribing/media/js && npm run build-css')


def purge_urls(paths_from_git, changed_in_static):
    """Turn 2 lists of filenames (changed in git, and in static) to a list
    of URLs to purge in Cloudflare.

    """
    urls = []
    if env.environment == 'production':
        base_url = 'https://openprescribing.net'
    else:
        base_url = 'http://staging.openprescribing.net'

    static_templates = {
        'openprescribing/templates/index.html': '',
        'openprescribing/templates/api.html': 'api/',
        'openprescribing/templates/about.html': 'about/',
        'openprescribing/templates/caution.html': 'caution/',
        'openprescribing/templates/how-to-use.html': 'how-to-use/'
    }
    for name in changed_in_static:
        if name.startswith('openprescribing/static'):
            urls.append("%s/%s" %
                        (base_url,
                         name.replace('openprescribing/static/', '')))

    for name in paths_from_git:
        if name in static_templates:
            urls.append("%s/%s" % (base_url, static_templates[name]))
    return urls


def log_deploy():
    current_commit = run("git rev-parse --verify HEAD")
    url = ("https://github.com/ebmdatalab/openprescribing/compare/%s...%s"
           % (env.previous_commit, current_commit))
    log_line = json.dumps({'started_at': str(env.started_at),
                           'ended_at': str(datetime.utcnow()),
                           'changes_url': url})
    run("echo '%s' >> deploy-log.json" % log_line)
    notify_newrelic(current_commit, url)
    if env.environment == 'production':
        notify_slack(
            "A #deploy just happened. Changes here: %s" % url)


def checkpoint(force_build):
    env.started_at = datetime.utcnow()
    with settings(warn_only=True):
        inited = run('git status').return_code == 0
        if not inited:
            git_init()
        if run('file .venv').return_code > 0:
            venv_init()
    env.previous_commit = run('git rev-parse --verify HEAD')
    run('git fetch')
    env.next_commit = run('git rev-parse --verify origin/%s' % env.branch)
    env.changed_files = set(
        run("git diff --name-only %s %s" %
            (env.previous_commit, env.next_commit), pty=False)
        .split())
    if not force_build and env.next_commit == env.previous_commit:
        abort("No changes to pull from origin!")


def deploy_static():
    bootstrap_environ = {
        'MAILGUN_WEBHOOK_USER': 'foo',
        'MAILGUN_WEBHOOK_PASS': 'foo'}
    with shell_env(**bootstrap_environ):
        with prefix('source .venv/bin/activate'):
            run('cd openprescribing/ && '
                'python manage.py collectstatic -v0 --noinput')


def run_migrations():
    if env.environment == 'production':
        with prefix('source .venv/bin/activate'):
            run('cd openprescribing/ && python manage.py migrate')
    else:
        warn("Refusing to run migrations in staging environment")


@task
def graceful_reload():
    result = sudo_script('graceful_reload.sh %s' % env.app)
    if result.failed:
        # Use the error from the bash command(s) rather than rely on
        # noisy (and hard-to-interpret) output from fabric
        abort(result)


def find_changed_static_files():
    changed = run(
        "find %s/openprescribing/static -type f -newermt '%s'" %
        (env.path, env.started_at.strftime('%Y-%m-%d %H:%M:%S'))).split()
    return map(lambda x: x.replace(env.path + '/', ''), [x for x in changed])


@task
def list_cloudflare_zones():
    url = 'https://api.cloudflare.com/client/v4/zones'
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Key": os.environ['CF_API_KEY'],
        "X-Auth-Email": os.environ['CF_API_EMAIL']
    }
    result = json.loads(
        requests.get(url, headers=headers,).text)
    zones = map(lambda x: {'name': x['name'], 'id': x['id']},
                [x for x in result["result"]])
    print(json.dumps(zones, indent=2))


def clear_cloudflare():
    url = 'https://api.cloudflare.com/client/v4/zones/%s'
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Key": os.environ['CF_API_KEY'],
        "X-Auth-Email": os.environ['CF_API_EMAIL']
    }
    data = {'purge_everything': True}
    print("Purging from Cloudflare:")
    print(data)
    result = json.loads(
        requests.delete(url % ZONE_ID + '/purge_cache',
                        headers=headers, data=json.dumps(data)).text)
    if result['success']:
        print("Cloudflare clearing succeeded: %s" %
              json.dumps(result, indent=2))
    else:
        warn("Cloudflare clearing failed: %s" %
             json.dumps(result, indent=2))


def setup_cron():
    crontab_path = '%s/deploy/crontab-%s' % (env.path, env.app)
    if exists(crontab_path):
        sudo_script('setup_cron.sh %s' % crontab_path)


@task
def deploy(environment, force_build=False, branch='master'):
    if 'CF_API_KEY' not in os.environ:
        abort("Expected variables (e.g. `CF_API_KEY`) not found in environment")
    if environment not in environments:
        abort("Specified environment must be one of %s" %
              ",".join(environments.keys()))
    env.app = environments[environment]
    env.environment = environment
    env.path = "/webapps/%s" % env.app
    env.branch = branch
    setup_sudo()
    with cd(env.path):
        checkpoint(force_build)
        git_pull()
        pip_install()
        npm_install()
        npm_install_deps(force_build)
        npm_build_js()
        npm_build_css(force_build)
        deploy_static()
        run_migrations()
        graceful_reload()
        clear_cloudflare()
        setup_cron()
        log_deploy()
