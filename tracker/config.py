"""Loads the two YAML files into a single settings dict.

Settings you'll rarely touch (keywords, filters, notification channels) live in
config/config.yaml; the company list you'll keep adding to lives in
config/companies.yaml, named by config.yaml's `companies_file` key. They're
merged here so the rest of the code only ever sees one dict.
"""

import yaml

from tracker import paths
from tracker import sources


def load_config():
    with open(paths.CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    companies_filename = cfg.get("companies_file", "companies.yaml")
    companies_path = paths.CONFIG_DIR / companies_filename
    if not companies_path.exists():
        raise FileNotFoundError(
            f"companies_file '{companies_filename}' (referenced in config/config.yaml) not found "
            f"in {paths.CONFIG_DIR}. This is the file with your actual list of companies to "
            "scrape - see config/companies.yaml for the expected format."
        )
    with open(companies_path, "r", encoding="utf-8") as f:
        companies_cfg = yaml.safe_load(f) or {}

    cfg["sources"] = companies_cfg.get("sources", [])
    sources.configure_browser(cfg.get("browser_rendering", {}))
    return cfg
