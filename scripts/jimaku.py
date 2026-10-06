"""jimaku.cc lookups through its API. An API key is required: create one on your
jimaku account page and put it in config.json as "jimaku_api_key".

Results are cached in cache/jimaku/ so re-runs do not hit the API again.
"""
import json, os, sys, urllib.parse
from common import CACHE, load_config, load_json, save_json, http_get

API = "https://jimaku.cc/api"
STORE = os.path.join(CACHE, "jimaku")
os.makedirs(STORE, exist_ok=True)


def _headers():
    key = load_config().get("jimaku_api_key") or ""
    if not key:
        sys.exit("jimaku needs an API key: log in at https://jimaku.cc, open your account page, create a key, "
                 "and set \"jimaku_api_key\" in ~/.anki-anime-planner/config.json")
    return {"Authorization": key}


def _cached(name, fetch):
    path = os.path.join(STORE, name)
    data = load_json(path)
    if data is None:
        data = fetch()
        save_json(path, data)
    return data


def _entry(d):
    return {k: d.get(k) for k in ("id", "name", "english_name", "japanese_name", "anilist_id", "flags")}


def by_anilist(anilist_id):
    """The jimaku entry for an AniList id, or None."""
    rows = _cached(f"anilist_{anilist_id}.json",
                   lambda: json.loads(http_get(f"{API}/entries/search?anilist_id={anilist_id}", headers=_headers())))
    return _entry(rows[0]) if rows else None


def search(title):
    """Entries whose name matches a free-text title, for shows that are not on the MAL list."""
    rows = _cached(f"q_{urllib.parse.quote(title, safe='')[:120]}.json",
                   lambda: json.loads(http_get(f"{API}/entries/search?query={urllib.parse.quote(title)}", headers=_headers())))
    return [_entry(r) for r in rows if r.get("anilist_id")]


def files(entry_id):
    """{file name: download url} for an entry's subtitle files."""
    rows = json.loads(http_get(f"{API}/entries/{entry_id}/files", headers=_headers()))
    return {r["name"]: r["url"] for r in rows if r.get("url")}
