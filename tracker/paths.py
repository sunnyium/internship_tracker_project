"""Every filesystem path the project uses, resolved from the location of this
file rather than from the current working directory.

Previously each module did its own `Path(__file__).parent / "thing"`, which
worked only because every file sat in one flat directory. Centralizing it here
means the layout is described in exactly one place, and a script run from
anywhere still finds the config and the database.
"""

from pathlib import Path

# tracker/paths.py -> tracker/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

CONFIG_FILE = CONFIG_DIR / "config.yaml"
RESET_LIST_FILE = CONFIG_DIR / "companies_to_reset.txt"

# Not in version control - it's per-machine state, and it's what keeps the
# tracker from re-notifying you about every posting it has ever seen.
DB_FILE = DATA_DIR / "seen_jobs.db"
