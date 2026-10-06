"""Find anime video files under the configured scan roots and local subtitle packs.

Writes cache/disk.json: shows grouped by parsed title and season, with their files
and distinct episode numbers, plus the titles available in local subtitle packs
(folders named by MAL title). Folders listed in config "skip_dirs" are not entered,
nothing deeper than "scan_depth" levels is entered, and a directory whose modification
time has not changed since the last scan is reused from cache/dirlist.json instead of
being listed again, so repeat scans touch only what changed.
"""
import fnmatch, os, re, sys, threading, time
import anitopy
from common import CACHE, load_config, load_json, save_json, log, scan_roots, skip_dirs

VIDEO = {".mkv", ".mp4", ".avi", ".webm", ".m4v", ".ts"}
SUB = {".srt", ".ass", ".ssa"}
MIN_SIZE = 40 * 1024 * 1024
# Folder names that describe a container, not a show; the scanner looks further up for the title.
GENERIC = re.compile(r"^(season ?\d+|s\d+|specials?|extras?|featurettes?|bonus|ova|ovas|movies?|films?|bd|disc ?\d+|\d+|"
                     r"watched|unwatched|anime|animes?|other|misc|boring|dropped.*|old|new|subs?|video|videos|downloads?\d*|"
                     r"complete|.*\bmini\b.*|arc ?\d+.*|vol(ume)? ?\d+)$", re.I)
# Release-name junk that anitopy leaves inside the title.
JUNK = re.compile(r"\b(av1|x26[45]|h\.?26[45]|hevc|avc|10 ?bits?|8 ?bits?|hi10p?|\d{3,4}p|\d{3,4}x\d{3,4}|bd|bdrip|bluray|blu-ray|"
                  r"webrip|web-dl|web|dl|hdtv|dvd(rip)?|dual[ -]?audio|multi[ -]?subs?|eng[ -]?subs?|subbed|dubbed|uncensored|"
                  r"complete|batch|remux|aac|flac|opus|ac3|eac3|dd\+?|ddp\d(\.\d)?|truehd|dts|\d\.\d|v\d|end|fin|final)\b", re.I)
EPISODE_TITLE = re.compile(r"^\d{1,3}\s*[-–.]\s*\S")           # "01 - Boy Meets Fluffy Girl"


def fallback_parse(name):
    stem = re.sub(r"[\[\(].*?[\]\)]", " ", os.path.splitext(name)[0])
    m = re.search(r"\bS(\d+)E(\d+)\b|\s-\s*(\d{1,3})\b", stem, re.I)
    title = stem[:m.start()] if m else stem
    return {"anime_title": title.strip(" -_."), "anime_season": m.group(1) if m and m.group(1) else None,
            "episode_number": (m.group(2) or m.group(3)) if m else None}


def parse(name):
    """anitopy's parse, guarded: it loops forever on names like "Show - S01E07 -.mkv"
    and raises on some bracket layouts, so it runs in a worker thread with a timeout
    and a plain regex parse takes over when it misbehaves."""
    name = re.sub(r"(\s*[-–_]\s*)+(?=\.[A-Za-z0-9]{2,4}$|$)", "", name.strip())
    result = {}

    def run():
        try:
            result.update(anitopy.parse(name) or {})
        except Exception:
            pass
    worker = threading.Thread(target=run, daemon=True); worker.start(); worker.join(2)
    p = result if not worker.is_alive() and result else fallback_parse(name)
    if worker.is_alive():
        log(f"anitopy hung on {name!r}, used fallback parse")
    title = p.get("anime_title") or ""
    season = p.get("anime_season")
    if isinstance(season, list):
        season = season[0]
    episode = p.get("episode_number")
    if isinstance(episode, list):
        episode = episode[0]
    m = re.search(r"\b(\d+)(?:st|nd|rd|th) season\b|\bseason (\d+)\b", title, re.I)
    if m and not season:
        season, title = (m.group(1) or m.group(2)), title[:m.start()].strip()
    title = JUNK.sub(" ", title)
    title = re.sub(r"\s*[-–_.]\s*$|^\s*[-–_.]\s*", "", title)
    title = re.sub(r"\(\s*\)|\[\s*\]", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" -_.")
    season = int(season) if season and str(season).isdigit() else None
    episode = int(episode) if episode and str(episode).isdigit() else None
    return title, season, episode


def show_title(path, root):
    """Title and season for one video file: the file's own name, unless a non-generic
    ancestor folder names the show better (episode-title files, season subfolders)."""
    title, season, episode = parse(os.path.basename(path))
    rel = os.path.relpath(os.path.dirname(path), root).split(os.sep) if os.path.dirname(path) != root else []
    for name in reversed([n for n in rel if n not in (".", "")]):
        if GENERIC.match(name):
            continue
        folder_title, folder_season, _ = parse(name)
        if folder_title and (not title or EPISODE_TITLE.match(os.path.basename(path)) or len(title) < 4
                             or folder_title.lower().startswith(title.lower()) or title.lower() in folder_title.lower()
                             or len(folder_title) >= len(title)):
            title, season = folder_title, folder_season or season
        break
    return title, season, episode


def list_videos(root, skip, max_depth, old):
    """Yield (path, size) for video files under root. Directories are listed with
    scandir; one whose mtime matches the previous scan reuses its cached listing."""
    new = {}
    stack = [(root, 0)]
    started, dirs_seen = time.time(), 0
    while stack:
        d, depth = stack.pop()
        dirs_seen += 1
        try:
            mtime = os.stat(d).st_mtime
            cached = old.get(d)
            if cached and cached["mtime"] == mtime:
                entry = cached
            else:
                entry = {"mtime": mtime, "subdirs": [], "videos": []}
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                entry["subdirs"].append(e.name)
                            elif os.path.splitext(e.name)[1].lower() in VIDEO:
                                size = e.stat().st_size
                                if size >= MIN_SIZE:
                                    entry["videos"].append([e.name, size])
                        except OSError:
                            continue
        except OSError as err:
            log(f"skip {d}: {err}"); continue
        new[d] = entry
        for name, size in entry["videos"]:
            yield os.path.join(d, name), size
        if depth < max_depth:
            for name in entry["subdirs"]:
                if not any(fnmatch.fnmatch(name.lower(), pat) for pat in skip):
                    stack.append((os.path.join(d, name), depth + 1))
        if dirs_seen % 2000 == 0:
            log(f"  {dirs_seen} directories, {time.time() - started:.0f}s, at {d[:70]}")
    old.update(new)


def main():
    cfg = load_config()
    skip = skip_dirs(cfg)
    max_depth = int(cfg.get("scan_depth", 6))
    dirlist_path = os.path.join(CACHE, "dirlist.json")
    dirlist = {} if "--rescan" in sys.argv else (load_json(dirlist_path) or {})
    shows, scanned = {}, 0
    started = time.time()
    roots = scan_roots(cfg)
    log(f"scanning {', '.join(roots)}")
    for root in roots:
        for path, size in list_videos(root, skip, max_depth, dirlist):
            scanned += 1
            title, season, episode = show_title(path, root)
            if not title or re.fullmatch(r"[\d\s.-]+", title):
                continue
            key = f"{title.lower()}||{season or ''}"
            s = shows.setdefault(key, {"title": title, "season": season, "files": [], "dirs": set(), "episodes": set()})
            s["files"].append(path); s["dirs"].add(os.path.dirname(path))
            if episode is not None:
                s["episodes"].add(episode)
    for s in shows.values():
        s["dirs"] = sorted(s["dirs"]); s["files"].sort(); s["episodes"] = sorted(s["episodes"])

    packs = {}
    for pack in cfg["local_sub_packs"]:
        for title in sorted(os.listdir(pack)):
            folder = os.path.join(pack, title)
            if not os.path.isdir(folder):
                continue
            subs = [os.path.join(dp, f) for dp, _, fs in os.walk(folder) for f in fs if os.path.splitext(f)[1].lower() in SUB]
            if subs:
                packs[title] = {"folder": folder, "subs": sorted(subs)}

    save_json(dirlist_path, dirlist)
    save_json(os.path.join(CACHE, "disk.json"), {"shows": sorted(shows.values(), key=lambda s: s["title"].lower()), "sub_packs": packs})
    print(f"{len(dirlist)} directories in {time.time() - started:.0f}s, {scanned} video files, {len(shows)} shows kept ({sum(len(s['files']) for s in shows.values())} files), {len(packs)} titles in local sub packs")


if __name__ == "__main__":
    main()
