from workspace.utils import repos_config


config = repos_config.load_config()

ORGS = config["shorthands"]["orgs"]
TEAMS = config["shorthands"]["teams"]
