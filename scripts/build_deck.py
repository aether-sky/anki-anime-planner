"""Build a subs2srs-style Anki deck from an MKV + Japanese subs + English subs.

usage: python build_deck.py VIDEO JA_SUBS EN_SUBS OUT.apkg --deck "Show::S01E01" [--audio 0:1] [--episode S01E01] [--dry-run]
"""
import argparse, hashlib, html, os, re, shutil, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor
import pysubs2, genanki
from common import ffmpeg_paths

FFMPEG, FFPROBE = ffmpeg_paths()
DIALOGUE_STYLES = {"Default", "Italics", "Top-Alt", "Dialogue", "Main", "Main - Top"}
MIN_CHARS = 8          # lines with fewer kana/kanji than this are tagged "short" for the user to suspend
CONTEXT = 2            # lines before/after on the back
START_TRIM = 0.05      # seconds shaved off the start of the cue
END_PAD = 0.15         # seconds added after the cue; the neighbour clamp below still keeps the next line out
NEIGHBOR_GAP = 0.02    # clips never come closer than this to the adjacent line
THUMB_W = 320          # thumbnail width in px

KANA_KANJI = re.compile(r"[ぁ-ゖァ-ヺー一-鿿々〆ヵヶ]")


def clean_ja(t):
    t = re.sub(r"\{[^}]*\}", "", t)                        # ASS override tags
    t = t.replace("\\N", "").replace("\\n", "")
    t = re.sub(r"\(([ぁ-ゖァ-ヺー]+)\)", "", t)              # furigana 凱旋(がいせん)
    t = re.sub(r"（[^）]*）", "", t)                          # （speaker） and （SFX）
    return t.strip()


def clean_en(t):
    t = re.sub(r"\{[^}]*\}", "", t)                        # tags + QC comments
    t = t.replace("\\N", " ").replace("\\n", " ")
    return re.sub(r"\s+", " ", t).strip()


def load_ja(path):
    """Closed-caption subs re-emit a line every time another line appears or
    disappears, so identical consecutive cues are merged back into one."""
    out = []
    for e in sorted(pysubs2.load(path), key=lambda e: (e.start, e.end)):
        if "♪" in e.text:
            continue
        txt = clean_ja(e.text)
        if not txt or not KANA_KANJI.search(txt):
            continue
        top = "\\an8" in e.text                         # background speaker, shown at top
        speaker = bool(re.match(r"(\{[^}]*\})?（", e.text))
        prev = out[-1] if out else None
        if prev and prev["ja"] == txt and prev["top"] == top and e.start - prev["end"] < 200:
            prev["end"] = max(prev["end"], e.end)
            continue
        out.append(dict(start=e.start, end=e.end, orig=e.start, ja=txt, top=top, speaker=speaker))
    return out


def load_en(path):
    out = []
    for e in pysubs2.load(path):
        if e.style not in DIALOGUE_STYLES:
            continue
        txt = clean_en(e.text)
        if txt:
            out.append(dict(start=e.start, end=e.end, en=txt, top="Top" in e.style))
    out.sort(key=lambda c: c["start"])
    return out


def overlap(a, b):
    return max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def match_en(cue, en_cues):
    """English cues in the same screen position (main vs top) that overlap the
    Japanese cue by >=40% of the shorter one. A main line with no match also
    tries Top-Alt; a background (top) line never borrows the main line's text."""
    for want_top in ((True,) if cue["top"] else (False, True)):
        hits = []
        for e in en_cues:
            if e["top"] != want_top or e["end"] < cue["start"] or e["start"] > cue["end"]:
                continue
            ov = overlap(cue, e)
            shorter = min(cue["end"] - cue["start"], e["end"] - e["start"]) or 1
            if ov / shorter >= 0.4:
                hits.append(e["en"])
        if hits:
            return " ".join(hits)
    return ""


def retime(ja, en, window=8, max_gap=1200):
    """Shift each Japanese cue by the rolling median of (nearest English start -
    Japanese start) over its neighbours, so the clips follow the English track's
    timing even when the BD masters differ by a few hundred ms in places."""
    import statistics
    starts = sorted(e["start"] for e in en)
    diffs = []
    for c in ja:
        near = min(starts, key=lambda x: abs(x - c["start"])) if starts else None
        diffs.append(near - c["start"] if near is not None and abs(near - c["start"]) < max_gap else None)
    matched = [(i, d) for i, d in enumerate(diffs) if d is not None]
    if len(matched) < 10:
        return 0
    shifts = []
    for i, c in enumerate(ja):
        pos = min(range(len(matched)), key=lambda k: abs(matched[k][0] - i))
        lo, hi = max(0, pos - window), pos + window + 1
        shifts.append(int(statistics.median(d for _, d in matched[lo:hi])))
    for c, sh in zip(ja, shifts):
        c["start"] += sh; c["end"] += sh
    return statistics.median(shifts)


def merge_fragments(ja):
    """Join consecutive same-speaker cues that share one English translation,
    i.e. a sentence the captioner split across several lines."""
    out = []
    for c in ja:
        prev = out[-1] if out else None
        if (prev and c["en"] and c["en"] == prev["en"] and not c["speaker"]
                and c["top"] == prev["top"] and c["start"] - prev["end"] < 500):
            prev["ja"] += " " + c["ja"]
            prev["end"] = max(prev["end"], c["end"])
            continue
        out.append(c)
    return out


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


CSS = """.card{font-family:"Noto Sans JP","Yu Gothic",sans-serif;text-align:center;background:#fafafa;color:#222}
.thumb img{width:320px;max-width:90%;border-radius:6px;box-shadow:0 2px 6px rgba(0,0,0,.3)}
.ja{font-size:30px;margin:14px 0 6px}.en{font-size:18px;color:#444}
.ctx{text-align:left;max-width:560px;margin:10px auto;font-size:15px;color:#777;line-height:1.5}
.ctx .line{margin:4px 0}.ctx .line span,.ctx .cen{display:block;font-size:12px;color:#999}
.ctx .cur{color:#222;background:#fff3c4;padding:4px 8px;border-radius:4px;margin:6px 0}
.ctx .cur .cen{color:#666}.src{font-size:11px;color:#aaa;margin-top:8px}"""

FRONT = '<div class="thumb">{{Image}}</div>{{Audio}}'
BACK = ('<div class="thumb">{{Image}}</div><div class="ja">{{Expression}}</div><hr>'
        '<div class="ctx">{{ContextBefore}}'
        '<div class="cur">{{Expression}}</div>'
        '{{ContextAfter}}</div>'
        '<div class="src">{{Episode}} · {{Time}}</div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("ja"); ap.add_argument("en"); ap.add_argument("out")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--deck", required=True, help='deck name, e.g. "Sousou no Frieren::S01E01"')
    ap.add_argument("--audio", default="0:1", help="ffmpeg stream specifier of the Japanese audio track")
    ap.add_argument("--episode", default=None, help="episode tag like S01E01 when the filename lacks one")
    a = ap.parse_args()

    tag = re.search(r"S\d+E\d+", os.path.basename(a.video))
    ep = a.episode or (tag.group(0) if tag else os.path.splitext(os.path.basename(a.video))[0])
    deck_name = a.deck
    show_tag = re.sub(r"\s+", "-", deck_name.split("::")[0].lower())

    ja = load_ja(a.ja); en = load_en(a.en)
    duration = float(subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                                     "format=duration", "-of", "csv=p=0", a.video], capture_output=True, text=True).stdout or 0)
    if duration:
        before = len(ja)
        ja = [c for c in ja if c["start"] / 1000 < duration - 0.5]      # cues past the end of the video have no media
        if len(ja) < before:
            print(f"{ep}: dropped {before - len(ja)} cues timed past the end of the video")
    shift = retime(ja, en)
    print(f"{ep}: retimed Japanese cues to the English track (median shift {shift:+.0f} ms)")
    for c in ja:
        c["en"] = match_en(c, en)
    ja = merge_fragments(ja)
    cards = list(range(len(ja)))
    short = {i for i, c in enumerate(ja) if len(KANA_KANJI.findall(c["ja"])) < MIN_CHARS}
    print(f"{ep}: {len(ja)} dialogue lines, {len(cards)} cards, {len(short)} of them tagged short, "
          f"{sum(1 for i in cards if not ja[i]['en'])} without an English match")

    if a.dry_run:
        for i in cards:
            c = ja[i]
            print(f"{c['start']/1000:8.2f}  {'short ' if i in short else '      '}{c['ja']}  ||  {c['en']}")
        return

    model = genanki.Model(
        1607392319, "subs2srs listening",
        fields=[{"name": f} for f in
                ["SortKey", "Expression", "Meaning", "Audio", "Image",
                 "ContextBefore", "ContextAfter", "Time", "Episode"]],
        templates=[{"name": "Listening", "qfmt": FRONT, "afmt": BACK}],
        css=CSS,
    )
    deck = genanki.Deck(int(hashlib.md5(deck_name.encode()).hexdigest()[:8], 16), deck_name)
    tmp = tempfile.mkdtemp(prefix="s2s_")
    try:
        build(a, ep, deck_name, show_tag, ja, cards, short, model, deck, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build(a, ep, deck_name, show_tag, ja, cards, short, model, deck, tmp):
    # The Japanese track is pulled out once, without re-encoding, and every clip is cut from it.
    track = os.path.join(tmp, "ja.mka")
    run([FFMPEG, "-v", "error", "-y", "-i", a.video, "-map", a.audio, "-c", "copy", track])
    codec = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "a:0",
                            "-show_entries", "stream=codec_name", "-of", "csv=p=0", track],
                           capture_output=True, text=True).stdout.strip()
    # Lossy sources are cut without re-encoding; a lossless source gets one high-quality mp3 pass,
    # since FLAC clips would make the deck enormous.
    lossless = codec in ("flac", "pcm_s16le", "pcm_s24le", "alac", "truehd")
    clip_ext = ".mp3" if lossless else {"aac": ".m4a", "opus": ".ogg", "vorbis": ".ogg", "mp3": ".mp3"}.get(codec, ".mka")

    def make_media(i):
        c = ja[i]
        s = c["start"] / 1000 + START_TRIM
        e = c["end"] / 1000 + END_PAD
        # A background line (top of screen) is spoken over the main line, so only a
        # neighbour in the same screen position limits the clip.
        previous = next((p for p in reversed(ja[:i]) if p["top"] == c["top"]), None)
        following = next((n for n in ja[i + 1:] if n["top"] == c["top"]), None)
        if previous:
            s = max(s, previous["end"] / 1000 + NEIGHBOR_GAP)
        if following:
            e = min(e, following["start"] / 1000 - NEIGHBOR_GAP)
        if e - s < 0.5:                       # neighbours squeezed it; fall back to the raw cue
            s, e = c["start"] / 1000, c["end"] / 1000
        s = max(0, s)
        base = f"{ep}_{c['orig']:07d}"
        clip = os.path.join(tmp, base + clip_ext); jpg = os.path.join(tmp, base + ".jpg")
        encode = ["-codec:a", "libmp3lame", "-q:a", "0"] if lossless else ["-c", "copy"]
        run([FFMPEG, "-v", "error", "-y", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", track, *encode, clip])
        run([FFMPEG, "-v", "error", "-y", "-ss", f"{(c['start'] + c['end']) / 2000:.3f}", "-i", a.video,
             "-frames:v", "1", "-vf", f"scale={THUMB_W}:-2", "-q:v", "3", jpg])
        return i, clip, jpg

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = {i: (m, j) for i, m, j in ex.map(make_media, cards)}

    def ctx_html(idx_list):
        return "".join(
            f'<div class="line">{html.escape(ja[j]["ja"])}</div>'
            for j in idx_list)

    media = []
    for i in cards:
        c = ja[i]; clip, jpg = results[i]
        media += [clip, jpg]
        before = range(max(0, i - CONTEXT), i)
        after = range(i + 1, min(len(ja), i + 1 + CONTEXT))
        t = c["start"] // 1000
        note = genanki.Note(model=model, fields=[
            f"{ep}_{c['orig']:07d}", html.escape(c["ja"]), html.escape(c["en"]),
            f"[sound:{os.path.basename(clip)}]", f'<img src="{os.path.basename(jpg)}">',
            ctx_html(before), ctx_html(after), f"{t // 60:02d}:{t % 60:02d}", ep,
        ], guid=genanki.guid_for(deck_name, c["orig"]), tags=[show_tag, ep] + (["short"] if i in short else []))
        deck.add_note(note)

    pkg = genanki.Package(deck); pkg.media_files = media
    pkg.write_to_file(a.out)
    print(f"wrote {a.out} with {len(cards)} notes and {len(media)} media files")


if __name__ == "__main__":
    main()
