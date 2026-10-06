"""Shared paths, config and helpers for the anime-planner scripts.

Everything has a working default: the MAL user is the only thing a person must supply,
and it can be given on the command line. config.json is created on first run.
"""
import json, os, re, shutil, string, sys, time, urllib.error, urllib.request

DATA = os.path.join(os.path.expanduser("~"), ".anime-planner")
CACHE = os.path.join(DATA, "cache")
SUBS = os.path.join(CACHE, "subs")
CONFIG_PATH = os.path.join(DATA, "config.json")
USER_AGENT = "anime-planner/0.1 (personal study tool)"

DEFAULT_CONFIG = {
    "mal_user": "",
    "jimaku_api_key": "",
    "scan_roots": [],                      # empty = every local fixed drive (or the home folder off Windows)
    "skip_dirs": [],                       # globs added to the built-in list below
    "scan_depth": 6,
    "local_sub_packs": [],                 # folders of subtitle folders named by MAL title, optional
    "episodes_per_show": 3,
    "ankiconnect_url": "http://127.0.0.1:8765",
    "anki_field": "Expression",
    "ffmpeg": "",                          # path to ffmpeg or its bin folder; empty = PATH
    "known_max": 0.85,                     # a show with more lines than this below the known cut is too easy
    "reference_shows": [],
    "title_overrides": {},
}
# Folders that never hold anime and are slow or pointless to walk.
BUILTIN_SKIP_DIRS = ["$recycle.bin", "system volume information", "recovery", "windows", "program files*", "programdata",
                     "appdata", "node_modules", ".git", ".*", "steamlibrary", "steamapps", "*backup*", "msdownld.tmp",
                     "library", "applications", "proc", "sys", "dev"]

for d in (DATA, CACHE, SUBS):
    os.makedirs(d, exist_ok=True)


def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_json(CONFIG_PATH, DEFAULT_CONFIG)
    cfg = dict(DEFAULT_CONFIG); cfg.update(load_json(CONFIG_PATH))
    return cfg


def scan_roots(cfg):
    if cfg.get("scan_roots"):
        return cfg["scan_roots"]
    if os.name == "nt":
        return [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.isdir(f"{letter}:\\")]
    return [os.path.expanduser("~")]


def skip_dirs(cfg):
    return [s.lower() for s in BUILTIN_SKIP_DIRS + list(cfg.get("skip_dirs", []))]


def ffmpeg_paths():
    """(ffmpeg, ffprobe) from config "ffmpeg" (a path to ffmpeg or its bin folder), else PATH."""
    configured = load_config().get("ffmpeg") or ""
    if configured and os.path.isdir(configured):
        configured = os.path.join(configured, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    ffmpeg = configured if configured and os.path.exists(configured) else shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found: install it and put it on PATH, or set \"ffmpeg\" in config.json")
    ffprobe = os.path.join(os.path.dirname(ffmpeg), os.path.basename(ffmpeg).replace("ffmpeg", "ffprobe"))
    return ffmpeg, ffprobe


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def http_get(url, binary=False, retries=3, headers=None):
    """GET with retries for transient failures; a 4xx answer is final and raised at once."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                return body if binary else body.decode("utf-8")
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 or attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def http_post_json(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def norm_title(t):
    """Lowercase, strip punctuation and season words, for fuzzy title matching."""
    t = t.lower()
    t = re.sub(r"[\[\(【](?=[^\]\)】]*\d)[^\]\)】]*[\]\)】]", " ", t)      # drop tags like [1080p], keep [Oshi no Ko]
    t = re.sub(r"\b(the|season|s\d+|\d+(st|nd|rd|th)|part|cour|bd|bluray|web|uncensored)\b", " ", t)
    t = re.sub(r"[^a-z0-9ぁ-ゖァ-ヺ一-鿿 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def log(msg):
    print(msg, file=sys.stderr, flush=True)
