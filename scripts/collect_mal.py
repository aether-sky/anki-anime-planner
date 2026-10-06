"""Download a public MyAnimeList anime list into cache/mal.json.

usage: python collect_mal.py [USERNAME]   (default: mal_user from config)
"""
import json, sys, os
from common import CACHE, load_config, save_json, http_get, log

STATUS = {1: "watching", 2: "completed", 3: "on_hold", 4: "dropped", 6: "plan_to_watch"}


def main():
    cfg = load_config()
    user = sys.argv[1] if len(sys.argv) > 1 else cfg["mal_user"]
    if not user:
        sys.exit("no MAL user: pass one or set mal_user in config.json")
    entries, offset = [], 0
    while True:
        page = json.loads(http_get(f"https://myanimelist.net/animelist/{user}/load.json?status=7&offset={offset}"))
        entries += page
        log(f"offset {offset}: {len(page)} entries")
        if len(page) < 300:
            break
        offset += 300
    out = [{
        "mal_id": e["anime_id"], "title": e["anime_title"], "title_eng": e.get("anime_title_eng") or "",
        "status": STATUS.get(e["status"], str(e["status"])), "score": e.get("score", 0),
        "mal_score": e.get("anime_score_val") or None,
        "episodes": e.get("anime_num_episodes", 0), "type": e.get("anime_media_type_string", ""),
        "watched": e.get("num_watched_episodes", 0),
    } for e in entries]
    save_json(os.path.join(CACHE, "mal.json"), {"user": user, "entries": out})
    counts = {}
    for e in out:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    print(f"{len(out)} entries for {user}: {counts}")


if __name__ == "__main__":
    main()
