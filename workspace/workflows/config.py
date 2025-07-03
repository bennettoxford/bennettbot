TEAMS = [
    "Tech shared",
    "Team REX",
    "Team RAP",
    "Team PIN",
]

REPOS = {
    "actions-registry": {
        "org": "opensafely-core",
        "team": "Team REX",
    },
    "airlock": {
        "org": "opensafely-core",
        "team": "Team RAP",
    },
    "backend-server": {
        "org": "opensafely-core",
        "team": "Team RAP",
    },
    "bennett.ox.ac.uk": {
        "org": "ebmdatalab",
        "team": "Team REX",
    },
    "bennettbot": {
        "org": "bennettoxford",
        "team": "Team RAP",
    },
    "documentation": {
        "org": "opensafely",
        "team": "Tech shared",
    },
    "ehrql": {
        "org": "opensafely-core",
        "team": "Team RAP",
    },
    "ethelred": {
        "org": "opensafely-core",
        "team": "Team PIN",
    },
    "job-runner": {
        "org": "opensafely-core",
        "team": "Team RAP",
    },
    "job-server": {
        "org": "opensafely-core",
        "team": "Team REX",
    },
    "kissh": {
        "org": "bennettoxford",
        "team": "Team RAP",
    },
    "metrics": {
        "org": "ebmdatalab",
        "team": "Team REX",
    },
    "openprescribing": {
        "org": "bennettoxford",
        "team": "Team RAP",
    },
    "opensafely-cli": {
        "org": "opensafely-core",
        "team": "Team REX",
    },
    "opensafely.org": {
        "org": "ebmdatalab",
        "team": "Tech shared",
    },
    "opencodelists": {
        "org": "opensafely-core",
        "team": "Team REX",
    },
    "pipeline": {
        "org": "opensafely-core",
        "team": "Team RAP",
    },
    "python-docker": {
        "org": "opensafely-core",
        "team": "Team RAP",
    },
    "reports": {
        "org": "opensafely-core",
        "team": "Team REX",
    },
    "repo-template": {
        "org": "opensafely-core",
        "team": "Tech shared",
    },
    "sqlrunner": {
        "org": "opensafely-core",
        "team": "Team RAP",
    },
    "team-manual": {
        "org": "ebmdatalab",
        "team": "Team REX",
    },
    "tpp-database-utils": {
        "org": "opensafely-core",
        "team": "Team RAP",
    },
}

IGNORED_WORKFLOWS = {
    "opensafely-core/backend-server": [
        88048790,  # Disabled
    ],
    "opensafely/documentation": [
        65834242,  # [On workflow dispatch] Check docs with Vale
    ],
    "opensafely-core/airlock": [
        94122733,  # [Ignored on main, PR#277] Docs
    ],
    "opensafely-core/job-runner": [
        26915901,  # [On workflow call] Add software bill of materials to release (reusable)
        26915902,  # [On workflow call] Scan with Grype (reusable)
        25002877,  # [On PR] Dependency review
        2393224,  # [On PR] Tests
    ],
    "opensafely-core/pipeline": [
        77090712,  # [Disabled] Pin pydantic
    ],
    "opensafely-core/python-docker": [
        6866192,  # [On PR] Run tests
        21967294,  # [On PR] Dependabot auto-approve and enable auto-merge
    ],
    "opensafely-core/sqlrunner": [
        37329087,  # [On PR] Auto merge Dependabot PRs
    ],
    "bennettoxford/bennettbot": [
        32719413,  # [On PR] Auto merge Dependabot PRs
    ],
}

WORKFLOWS_KNOWN_TO_FAIL = {
    "opensafely/documentation": [
        25878886,  # Check links (expected to break, notifications handled elsewhere)
    ],
    "ebmdatalab/bennett.ox.ac.uk": [
        42498719,  # Check links (expected to break, notifications handled elsewhere)
    ],
    "ebmdatalab/opensafely.org": [
        26433647,  # Check links (expected to break, notifications handled elsewhere)
    ],
    "ebmdatalab/team-manual": [
        31178226,  # Check links (expected to break, notifications handled elsewhere)
    ],
}

CUSTOM_WORKFLOWS_GROUPS = {
    "check-links": {
        "header_text": "Link-checking workflows",
        "workflows": {
            "opensafely/documentation": [25878886],
            "ebmdatalab/bennett.ox.ac.uk": [42498719],
            "ebmdatalab/opensafely.org": [26433647],
            "ebmdatalab/team-manual": [31178226],
        },
    }
}
