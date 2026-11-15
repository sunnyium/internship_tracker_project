"""Every filesystem path this half of the project uses, resolved from the
location of this file rather than from the current working directory.

Deliberately separate from tracker/paths.py, and pointing at different files:
the two trackers share a project root and nothing else, so one can be reset,
deleted or rescheduled without disturbing the other.
"""

from pathlib import Path

# github_boards/paths.py -> github_boards/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

CONFIG_FILE = CONFIG_DIR / "github_boards.yaml"

# Not in version control - per-machine notification history, same as the
# career-page tracker's seen_jobs.db sitting next to it.
DB_FILE = DATA_DIR / "github_jobs.db"
