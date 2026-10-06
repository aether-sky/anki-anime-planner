"""Join the MAL list, the disk scan, local sub packs and jimaku into cache/matches.json.

Each MAL entry gets its AniList id (via AniList's public GraphQL), its jimaku entry
(by AniList id), the video files found on disk, and a local sub pack folder if one
is named after it. Disk shows that match nothing on MAL are looked up on jimaku by
name; the rest are listed under "unmatched_disk" for a person to resolve. Fixes go
in config.json "title_overrides" as {"disk title": mal_id}.
"""
import difflib, os, re, time
import jimaku
from common import CACHE, load_config, load_json, save_json, http_post_json, norm_title, log

ROMAN = {"ii": 2, "iii": 3, "iv": 4, "v": 5}
SEASON_WORDS = re.compile(r"\b(\d+(st|nd|rd|th) season|season \d+|part \d+|ii|iii|iv|s\d|\d)\b")


def anilist_ids(mal_ids):
    cache_path = os.path.join(CACHE, "anilist_map.json")
    cache = load_json(cache_path, {})
    missing = [m for m in mal_ids if str(m) not in cache]
    for i in range(0, len(missing), 50):
        batch = missing[i:i + 50]
        q = "query($ids:[Int]){Page(perPage:50){media(idMal_in:$ids,type:ANIME){id idMal}}}"
        r = http_post_json("https://graphql.anilist.co", {"query": q, "variables": {"ids": batch}})
        found = {m["idMal"]: m["id"] for m in r["data"]["Page"]["media"]}
        for m in batch:
            cache[str(m)] = found.get(m)
        log(f"anilist: {min(i + 50, len(missing))}/{len(missing)}")
        time.sleep(1)
    save_json(cache_path, cache)
    return {m: cache.get(str(m)) for m in mal_ids}


def season_of(title):
    """Season number implied by a title, 1 if none."""
    t = title.lower()
    m = re.search(r"(\d+)(?:st|nd|rd|th) season|season (\d+)|\bpart (\d+)|\b(ii|iii|iv|v)\b|\bs(\d)\b|\s(\d)$", t)
    if not m:
        return 1
    for g in m.groups():
        if g:
            return ROMAN.get(g, int(g) if g.isdigit() else 1)
    return 1


def build_index(items, title_keys):
    index = {}
    for item in items:
        for k in title_keys:
            if item.get(k):
                index.setdefault(norm_title(item[k]), []).append(item)
    return index


def best_match(show, index, title_key, cutoff):
    """Closest entry in index to a disk show, preferring the same season. Deterministic:
    ties break on the entry's own id."""
    want_season = show["season"] or 1
    names = {norm_title(show["title"]), norm_title(re.sub(r"\(.*?\)", " ", show["title"]))}   # with and without "(English title)"
    candidates = []
    keys = list(index)
    for n in names:
        close = set(difflib.get_close_matches(n, keys, n=8, cutoff=0.6))
        close.update(k for k in keys if min(len(n), len(k)) >= 6 and (k.startswith(n) or n.startswith(k)))
        for key in close:
            base = SEASON_WORDS.sub(" ", key).strip()
            sim = difflib.SequenceMatcher(None, n, base).ratio()
            if min(len(n), len(base)) >= 6 and (base.startswith(n) or n.startswith(base)):
                sim = max(sim, 0.9)                   # "code geass" vs "code geass hangyaku no lelouch"
            for e in index[key]:
                season_ok = season_of(e[title_key]) == want_season
                candidates.append((sim + (0.15 if season_ok else -0.3), sim, str(e.get("mal_id") or e.get("id")), e))
    if not candidates:
        return None, None
    best = max(candidates)
    return (best[3], f"fuzzy {best[1]:.2f}") if best[1] >= cutoff else (None, None)


def main():
    cfg = load_config()
    mal = load_json(os.path.join(CACHE, "mal.json"))["entries"]
    disk = load_json(os.path.join(CACHE, "disk.json"), {"shows": [], "sub_packs": {}})
    overrides = cfg.get("title_overrides", {})
    ids = anilist_ids([e["mal_id"] for e in mal])
    mal_index = build_index(mal, ("title", "title_eng"))

    matches = {}
    for e in mal:
        aid = ids.get(e["mal_id"])
        j = jimaku.by_anilist(aid) if aid else None
        matches[e["mal_id"]] = {**e, "key": str(e["mal_id"]), "anilist_id": aid, "jimaku_id": j["id"] if j else None,
                                "jimaku_name": j["name"] if j else None, "files": [], "disk_titles": [],
                                "local_subs": disk["sub_packs"].get(e["title"], {}).get("folder")}
    unmatched, disk_only = [], {}
    for show in disk["shows"]:
        if show["title"] in overrides:
            e, how = matches.get(overrides[show["title"]]), "override"
        else:
            e, how = best_match(show, mal_index, "title", 0.8)
            e = matches.get(e["mal_id"]) if e else None
        if e:
            e["files"] += show["files"]; e["disk_titles"].append(f"{show['title']} (S{show['season'] or 1}, {how})")
            continue
        # Not on the MAL list: a show on disk still counts if jimaku knows it.
        j, how = best_match(show, build_index(jimaku.search(show["title"]), ("name", "english_name", "japanese_name")), "name", 0.85)
        if j:
            e = disk_only.setdefault(j["id"], {
                "mal_id": None, "key": f"j{j['id']}", "title": j["name"], "title_eng": j["english_name"] or "", "status": "not_on_mal",
                "score": 0, "mal_score": None, "episodes": 0, "type": "", "watched": 0, "anilist_id": j["anilist_id"], "jimaku_id": j["id"],
                "jimaku_name": j["name"], "files": [], "disk_titles": [], "local_subs": disk["sub_packs"].get(j["name"], {}).get("folder")})
            e["files"] += show["files"]; e["disk_titles"].append(f"{show['title']} (S{show['season'] or 1}, {how})")
        else:
            unmatched.append({"title": show["title"], "season": show["season"], "files": len(show["files"]), "dir": show["dirs"][0]})
    matches.update(disk_only)

    out = {"shows": list(matches.values()), "unmatched_disk": unmatched}
    save_json(os.path.join(CACHE, "matches.json"), out)
    s = out["shows"]
    print(f"{len(s)} shows: {sum(1 for x in s if x['anilist_id'])} with AniList id, {sum(1 for x in s if x['jimaku_id'])} on jimaku, "
          f"{sum(1 for x in s if x['local_subs'])} in local sub packs, {sum(1 for x in s if x['files'])} on disk "
          f"({len(disk_only)} of them not on MAL); {len(unmatched)} disk shows unmatched")


if __name__ == "__main__":
    main()
