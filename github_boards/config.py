"""Loads config/github_boards.yaml and fills in the per-repo defaults.

Every repo entry leaves the file the same shape, so nothing downstream has to
write `cfg.get("branch", "HEAD")` twice. Validation happens here too and is
loud: a typo'd strategy name is a config error worth failing on immediately,
unlike a repo that happens to be unreachable this round.

    load_config() | the whole settings dict, with cfg["repos"] normalized
"""

import yaml

from github_boards import paths

VALID_STRATEGIES = {"json", "markdown", "yaml_dir", "auto"}

# Where each strategy looks when a repo entry doesn't name files itself.
DEFAULT_PATHS = {
    "json": [".github/scripts/listings.json", "listings.json"],
    "markdown": ["README.md"],
    "auto": [],
}

REPO_DEFAULTS = {
    "branch": "HEAD",             # HEAD follows whatever the default branch is
    "require_internship_title": True,
    "keyword_match": True,
    "dir": "data",
    "max_files": 150,
}


def load_config():
    """The parsed config, with cfg["repos"] normalized and validated."""
    with open(paths.CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    cfg.setdefault("settings", {})
    cfg.setdefault("notifications", {})
    cfg["repos"] = [_normalize_repo(r, i) for i, r in enumerate(cfg.get("repos", []))]
    return cfg


def _normalize_repo(repo_cfg, index):
    entry = dict(REPO_DEFAULTS)
    entry.update(repo_cfg or {})

    if not entry.get("repo"):
        raise ValueError(f"repos[{index}] in github_boards.yaml has no `repo: owner/name`")
    if entry["repo"].count("/") != 1:
        raise ValueError(f"repos[{index}]: `repo` must be 'owner/name', got {entry['repo']!r}")

    strategy = entry.get("strategy", "auto")
    if strategy not in VALID_STRATEGIES:
        raise ValueError(
            f"repos[{index}] ({entry['repo']}): unknown strategy {strategy!r}. "
            f"Use one of: {', '.join(sorted(VALID_STRATEGIES))}"
        )
    entry["strategy"] = strategy

    entry.setdefault("name", entry["repo"])
    if not entry.get("paths"):
        entry["paths"] = list(DEFAULT_PATHS.get(strategy, []))
    return entry
