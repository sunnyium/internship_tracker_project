"""
Reads config/companies_to_reset.txt and wipes tracked history for each
company listed there. Useful after fixing a broken source config, or if you
just want a company's tracking to start fresh.

This does NOT touch companies.yaml and does not stop monitoring a
company - it only resets what's been recorded as "seen" in the database.
To stop monitoring a company entirely, remove its entry from
config/companies.yaml directly.

Run from the project root with:
    python -m scripts.reset_companies
"""

from tracker import state
from tracker.paths import RESET_LIST_FILE


def read_company_names():
    if not RESET_LIST_FILE.exists():
        return []
    names = []
    for line in RESET_LIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return names


def run():
    state.init_db()
    names = read_company_names()

    if not names:
        print("No company names found in config/companies_to_reset.txt (nothing to do).")
        return

    for name in names:
        deleted = state.delete_source_records(name)
        if deleted or state.is_baselined(name) is False:
            print(f"Reset '{name}': removed {deleted} tracked job record(s). It will re-baseline on the next check.")
        else:
            print(f"'{name}': no records found (check that this matches the 'name' field in companies.yaml exactly).")

    # Clear the file so re-running the script doesn't repeat the reset endlessly
    RESET_LIST_FILE.write_text(
        "# List company names here (one per line, must match the \"name\" field\n"
        "# in companies.yaml exactly) to wipe their tracked history from the database.\n"
        "#\n"
        "# Run `python -m scripts.reset_companies` afterward to apply it. That deletes\n"
        "# all stored job records + the baseline flag for each listed company, so the\n"
        "# next check re-baselines it from scratch - existing postings won't\n"
        "# trigger notifications, only new ones from that point on.\n"
        "#\n"
        "# This only resets tracking data - it does NOT remove the source from\n"
        "# companies.yaml. To stop monitoring a company entirely, delete or comment\n"
        "# out its entry in companies.yaml directly.\n"
        "#\n"
        "# Lines starting with # are ignored. This file is cleared automatically\n"
        "# after each successful run of reset_companies.\n",
        encoding="utf-8",
    )
    print(f"\nDone. Cleared companies_to_reset.txt ({len(names)} compan{'y' if len(names) == 1 else 'ies'} processed).")


if __name__ == "__main__":
    run()
