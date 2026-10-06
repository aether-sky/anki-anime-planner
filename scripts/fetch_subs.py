"""Collect a few episodes of Japanese subtitles per show into cache/subs/<key>/.

Local sub packs are used first. Otherwise the show's jimaku file list is fetched and
the first N episodes are downloaded. Dropped shows that are not on disk are skipped.
usage: python fetch_subs.py [--only KEY ...]
"""
import os, re, shutil, sys, time
import jimaku
from common import CACHE, SUBS, load_config, load_json, save_json, http_get, log

SUB_EXT = (".srt", ".ass", ".ssa")
BAD = re.compile(r"chs|cht|zh|简|繁|ja-en|_en\b|english|with furigana|\.en\.", re.I)


def episode_of(name):
    base = re.sub(r"\[[^\]]*\]|\([^)]*\)|\d{3,4}p|x26[45]|10bit", " ", os.path.splitext(name)[0])
    if re.search(r"\b\d{1,3}\s*-\s*\d{1,3}\b", base):
        return None                                   # a range like 01-02 covers two episodes
    m = re.search(r"S\d+E(\d+)", base, re.I) or re.search(r"(?<![\d.])(\d{1,3})(?![\d.])", base[len(base) // 3:]) or re.search(r"(?<![\d.])(\d{1,3})(?![\d.])", base)
    return int(m.group(1)) if m else None


def usable(names):
    return [n for n in names if n.lower().endswith(SUB_EXT) and not BAD.search(n)]


def pick(names, n):
    """Up to n files, one per episode, preferring BD-timed groups and plain .srt/.ass."""
    def rank(name):
        return (0 if re.search(r"\bBD\b|BDRip|Blu-?ray", name, re.I) else 1, 0 if name.lower().endswith(".srt") else 1, name)
    chosen, seen = [], set()
    for name in sorted(usable(names), key=rank):
        ep = episode_of(name)
        key = ep if ep is not None else name
        if key in seen:
            continue
        seen.add(key); chosen.append(name)
        if len(chosen) >= n:
            break
    return chosen


def main():
    cfg = load_config(); n = cfg["episodes_per_show"]
    shows = load_json(os.path.join(CACHE, "matches.json"))["shows"]
    only = set(sys.argv[sys.argv.index("--only") + 1:]) if "--only" in sys.argv else None
    done = skipped = failed = 0
    for s in shows:
        if only and s["key"] not in only:
            continue
        if s["status"] == "dropped" and not s["files"]:
            continue
        folder = os.path.join(SUBS, s["key"]); meta_path = os.path.join(folder, "meta.json")
        if os.path.exists(meta_path):
            skipped += 1; continue
        try:
            if s["local_subs"]:
                files = sorted(f for f in os.listdir(s["local_subs"]) if f.lower().endswith(SUB_EXT))
                if not files:
                    files = [os.path.relpath(os.path.join(dp, f), s["local_subs"]) for dp, _, fs in os.walk(s["local_subs"]) for f in fs if f.lower().endswith(SUB_EXT)]
                chosen = pick(files, n); os.makedirs(folder, exist_ok=True)
                for i, name in enumerate(chosen):
                    shutil.copy(os.path.join(s["local_subs"], name), os.path.join(folder, f"{i}{os.path.splitext(name)[1].lower()}"))
                meta = {"source": "local", "files": chosen}
            elif s["jimaku_id"]:
                files = jimaku.files(s["jimaku_id"])
                chosen = pick(list(files), n)
                if not chosen:
                    log(f"{s['title']}: jimaku entry {s['jimaku_id']} has no usable Japanese files"); failed += 1; continue
                os.makedirs(folder, exist_ok=True)
                got = []
                for name in chosen:
                    try:
                        data = http_get(files[name], binary=True)
                    except Exception as e:
                        log(f"{s['title']}: {name}: {e}"); continue
                    open(os.path.join(folder, f"{len(got)}{os.path.splitext(name)[1].lower()}"), "wb").write(data)
                    got.append(name); time.sleep(0.5)
                if not got:
                    failed += 1; continue
                meta = {"source": "jimaku", "entry": s["jimaku_id"], "files": got}
            else:
                continue
            save_json(meta_path, meta); done += 1
            log(f"{s['title']}: {len(meta['files'])} files from {meta['source']}")
        except Exception as e:
            log(f"{s['title']}: FAILED {e}"); failed += 1
    print(f"fetched {done}, already had {skipped}, failed {failed}")


if __name__ == "__main__":
    main()
