"""Rebuild caption lines from a jimaku "with furigana" .ass file.

Those files place every word as its own positioned event (style Text) with the
reading above it (style Furigana). This joins the Text events that share a time
span into one line per caption, rows top to bottom, words left to right, and
writes a plain .ass that build_deck.py can read. Captions shown in the top half
of the frame get an {\\an8} tag so they count as background lines.

usage: python flatten_furigana.py IN.ass OUT.ass
"""
import re, sys
import pysubs2

POS = re.compile(r"\\pos\(([\d.]+),([\d.]+)\)")

src = pysubs2.load(sys.argv[1])
frame_height = int(src.info.get("PlayResY", 1080))
groups = {}
for e in src:
    if e.style != "Text":
        continue
    m = POS.search(e.text)
    x, y = (float(m.group(1)), float(m.group(2))) if m else (0.0, frame_height)
    word = re.sub(r"\{[^}]*\}", "", e.text).replace("\\h", " ").strip()
    if word:
        groups.setdefault((e.start, e.end), []).append((round(y / 20), x, word))

out = pysubs2.SSAFile()
out.info["PlayResX"] = src.info.get("PlayResX", "1920"); out.info["PlayResY"] = str(frame_height)
for (start, end), words in sorted(groups.items()):
    rows = {}
    for row, x, word in words:
        rows.setdefault(row, []).append((x, word))
    text = "\\N".join("".join(w for _, w in sorted(rows[r])) for r in sorted(rows))
    if min(rows) * 20 < frame_height / 2:
        text = "{\\an8}" + text
    out.append(pysubs2.SSAEvent(start=start, end=end, text=text))
out.save(sys.argv[2])
print(f"{len(src)} events -> {len(out)} captions")
