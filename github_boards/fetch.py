"""Getting bytes out of GitHub, politely.

    fetch_file() | one file's text from raw.githubusercontent, or NOT_MODIFIED
    list_tree()  | every path in a repo, one API call

Two hosts are involved and they have very different rules. raw.githubusercontent
serves file contents and is not part of the REST rate limit; api.github.com is,
and allows only 60 requests an hour unauthenticated, which is why the tree
listing is used by exactly one strategy and file contents never go through it.

Conditional requests matter more here than in the career-page tracker: the
Simplify listings file is ~10MB and changes a handful of times a day, so every
fetch sends the ETag from the last successful read and most rounds get a 304
with an empty body back. That is the difference between 10MB and 300 bytes per
repo per round, and it is also a faster "nothing changed" signal than parsing
14,000 entries to discover the same thing.
"""

import os

import requests

# GitHub asks for a descriptive User-Agent and will 403 some clients without
# one. The Accept header keeps the API pinned to the documented v3 shape.
HEADERS = {
    "User-Agent": "internship-tracker-github-boards/1.0 (personal job alert script)",
    "Accept": "application/vnd.github+json",
}
TIMEOUT = 30

RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"
TREE_URL = "https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"

# Distinct from None, which fetch_file uses for "this file isn't there".
NOT_MODIFIED = object()


def _auth_headers():
    """A token turns the API's 60 requests/hour into 5,000. Optional - only
    the yaml_dir strategy touches the API at all, so an unauthenticated run
    is fine until many such repos are configured."""
    headers = dict(HEADERS)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_file(repo, branch, path, etag=None):
    """Returns (text, etag) for one file in a repo.

    text is NOT_MODIFIED when the server confirms our cached copy is current,
    and None when the file doesn't exist on that branch - a 404 here is normal
    (it is how the `auto` strategy discovers which layout a repo uses), so it
    returns rather than raising. Anything else raises, because a 500 or a rate
    limit is a real failure and should be reported per repo, not silently
    treated as an empty list."""
    url = RAW_URL.format(repo=repo, branch=branch, path=path.lstrip("/"))
    headers = dict(HEADERS)
    if etag:
        headers["If-None-Match"] = etag

    response = requests.get(url, headers=headers, timeout=TIMEOUT)
    if response.status_code == 304:
        return NOT_MODIFIED, etag
    if response.status_code == 404:
        return None, None
    response.raise_for_status()
    return response.text, response.headers.get("ETag")


def list_tree(repo, branch="HEAD"):
    """Every file path in the repo, from one call to the git trees API.

    Used only by the yaml_dir strategy, where the alternative is guessing file
    names. The API caps a recursive tree and sets `truncated` when it did; that
    is reported rather than hidden, since a truncated tree means silently
    missing companies."""
    url = TREE_URL.format(repo=repo, branch=branch)
    response = requests.get(url, headers=_auth_headers(), timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    paths = [t["path"] for t in payload.get("tree", []) if t.get("type") == "blob"]
    return paths, bool(payload.get("truncated"))
