"""Sort scored shows into tiers and write plan.json and report.html in the data folder.

Each show's non-trivial lines split into below the learner's floor (the difficulty under
which they usually suspend a card rather than keep it, for whatever reason), in range, and
above their ceiling (where they start suspending again because lines are too hard). A show
is not worth mining when most lines sit below the floor, too hard when too many are above
the ceiling, in range otherwise. While
no ceiling has been found, nothing counts as too hard. Within a tier, higher rated shows
come first.
"""
import html, os
from common import DATA, CACHE, load_config, load_json, save_json

FLOOR_MAX = float(load_config()["floor_max"])        # more lines than this below the floor and the show is not worth mining
HARD_MAX = 0.4                 # more lines than this above the high cut is too hard for now
REWATCH_HARD_MAX = 0.55
TIERS = [
    ("tier1", "Tier 1: ready for mining", "In your range and already in your library. A deck is one command away."),
    ("tier2", "Tier 2: go get it", "In your range, on your MAL, not in your library."),
    ("rewatch", "Rewatch: comprehensible input", "Completed shows that land in or just above your range. Known plot makes harder lines cheaper."),
    ("tier3", "Tier 3: parked", "Too hard for now. Sorted by how close they are; they move up as your window moves."),
    ("easy", "Bottom shelf: mostly below your floor", "Most lines sit below your floor. Watch freely, little to mine."),
]
COLORS = {"trivial": "#cde2fb", "easy": "#86b6ef", "mid": "#2a78d6", "hard": "#104281"}


def tier_of(s, easy, hard):
    if easy is None:
        return None
    if easy > FLOOR_MAX:
        return "easy"
    if hard <= HARD_MAX:
        if s["files"]:
            return "tier1"
        if s["status"] in ("plan_to_watch", "watching", "on_hold"):
            return "tier2"
        return "rewatch"
    if hard <= REWATCH_HARD_MAX and s["status"] == "completed":
        return "rewatch"
    return "tier3"


def bar(r):
    t = r["trivial_share"]; rest = 1 - t
    easy, hard = rest * r["easy_share"], rest * r["hard_share"]
    seg = [("trivial", t), ("easy", easy), ("mid", rest - easy - hard), ("hard", hard)]
    title = ", ".join(f"{k} {v:.0%}" for k, v in seg)
    return f'<div class="bar" title="{title}">' + "".join(f'<i style="width:{v*100:.1f}%;background:{COLORS[k]}"></i>' for k, v in seg) + "</div>"


def main():
    shows = load_json(os.path.join(CACHE, "matches.json"))["shows"]
    scored = load_json(os.path.join(CACHE, "scores.json")); model = scored["model"]
    rows = []
    for s in shows:
        sc = scored["shows"].get(s["key"])
        if not sc or sc["easy_share"] is None:
            continue
        rows.append({**{k: s[k] for k in ("key", "mal_id", "title", "title_eng", "status", "episodes", "type", "jimaku_id")},
                     "my_score": s.get("score") or None, "mal_score": s.get("mal_score"),
                     "on_disk": len(s["files"]), "dirs": sorted({os.path.dirname(f) for f in s["files"]})[:3],
                     "tier": tier_of(s, sc["easy_share"], sc["hard_share"]), "easy_share": sc["easy_share"],
                     "hard_share": sc["hard_share"], "trivial_share": sc["trivial_share"], "mean_z": sc["mean_z"],
                     "coverage": sc.get("coverage"), "new_words": sc.get("new_words"),
                     "mid_share": round(1 - sc["easy_share"] - sc["hard_share"], 3),
                     "lines": sc["lines"], "hist": sc["hist"]})
    for r in rows:
        r["rating"] = r["my_score"] or r["mal_score"] or 0           # your own score outranks the crowd's
    rows.sort(key=lambda r: (-r["rating"], -r["mid_share"], r["title"]))   # then the richest in-range yield
    plan = {"model": {k: model.get(k) for k in ("provisional", "fitted_on", "cut_low", "cut_high")},
            "tiers": {k: [r for r in rows if r["tier"] == k] for k, _, _ in TIERS}}
    save_json(os.path.join(DATA, "plan.json"), plan)

    unscored = [s for s in shows if s["key"] not in scored["shows"] and s["status"] != "dropped"]
    if model["provisional"]:
        note = ("<p class=warn>Provisional: not enough evaluated Anki cards yet, so your floor and ceiling are guesses from the "
                "corpus, not from you. Suspend what you already know in an episode or two and re-run.</p>")
    else:
        note = (f"<p>Your range comes from {model['fitted_on']} cards you have evaluated. Below the <b>floor</b> you usually suspend a "
                "card rather than keep it; the tool does not know why, only that you do. "
                + ("The <b>ceiling</b>, where you start suspending lines as too hard, has <b>not been found yet</b>: nothing you have "
                   "evaluated was hard enough, so no show is marked too hard. Mine something harder and it will appear.</p>"
                   if model["cut_high"] is None else
                   "The <b>ceiling</b> is where you start suspending lines as too hard.</p>"))
    user = load_json(os.path.join(CACHE, "mal.json"))["user"]
    parts = [f"""<!doctype html><meta charset="utf-8"><title>Anime plan</title><style>
body{{font-family:system-ui,sans-serif;max-width:1000px;margin:32px auto;padding:0 16px;color:#0b0b0b;background:#fcfcfb}}
h2{{margin:36px 0 4px}} .desc{{color:#52514e;margin:0 0 12px}} .warn{{background:#fff3c4;padding:8px 12px;border-radius:6px}}
table{{border-collapse:collapse;width:100%}} td,th{{padding:6px 8px;border-bottom:1px solid #e6e5e1;text-align:left;font-size:14px;vertical-align:top}}
th{{color:#52514e;font-weight:500}} .bar{{display:flex;width:180px;height:10px;border-radius:4px;overflow:hidden;gap:2px;background:#f0efec}}
.bar i{{display:block;height:100%}} .num{{text-align:right;font-variant-numeric:tabular-nums}} .muted{{color:#52514e;font-size:12px}}
.legend i{{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:middle;margin:0 4px 0 12px}}
</style><h1>Anime plan for {html.escape(user)}</h1>{note}
<p class="muted">Within each tier, shows are ordered by rating: your own MAL score in bold, otherwise the MAL average. Ties by how many lines sit in your range.
"Vocab you know" is the share of a show's words (by occurrence) that you know: words on cards you suspended because they were
easy, or on cards you have learned (kept, interval of three weeks or more). That is {model.get('vocabulary', 0)} distinct words so far,
from {model.get('easy_cards', 0)} easy and {model.get('learned_cards', 0)} learned cards; it grows as you study.</p>
<p class="legend muted">Share of lines: <i style="background:{COLORS['trivial']}"></i>trivial (under 10 characters)
<i style="background:{COLORS['easy']}"></i>below your floor <i style="background:{COLORS['mid']}"></i>in your range <i style="background:{COLORS['hard']}"></i>above your ceiling (too hard).
Bottom shelf = over {FLOOR_MAX:.0%} below the floor; parked = over {HARD_MAX:.0%} above the ceiling.</p>"""]
    for key, title, desc in TIERS:
        rs = plan["tiers"][key]
        parts.append(f"<h2>{title} <span class=muted>({len(rs)})</span></h2><p class=desc>{desc}</p>")
        if not rs:
            continue
        parts.append("<table><tr><th>Show</th><th>Rating</th><th>Lines</th><th>Vocab you know</th><th>Below floor</th><th>In range</th><th>Hard</th><th></th><th>MAL</th><th>Where</th></tr>")
        for r in rs:
            where = ("in your library: " + html.escape(r["dirs"][0])) if r["on_disk"] else (f'<a href="https://jimaku.cc/entry/{r["jimaku_id"]}">jimaku</a>' if r["jimaku_id"] else "")
            coverage = "" if r["coverage"] is None else f"{r['coverage']:.0%}"
            rating = (f"<b>{r['my_score']}</b> <span class=muted>({r['mal_score']})</span>" if r["my_score"] and r["mal_score"]
                      else f"<b>{r['my_score']}</b>" if r["my_score"] else f"{r['mal_score']}" if r["mal_score"] else "")
            parts.append(f"<tr><td>{html.escape(r['title'])}<div class=muted>{html.escape(r['title_eng'] or '')}</div></td>"
                         f"<td class=num>{rating}</td><td class=num>{r['lines']}</td><td class=num>{coverage}</td><td class=num>{r['easy_share']:.0%}</td>"
                         f"<td class=num>{r['mid_share']:.0%}</td><td class=num>{r['hard_share']:.0%}</td><td>{bar(r)}</td>"
                         f"<td>{r['status'].replace('_', ' ')}</td><td class=muted>{where}</td></tr>")
        parts.append("</table>")
    if unscored:
        parts.append(f"<h2>No subtitles found <span class=muted>({len(unscored)})</span></h2><p class=muted>" +
                     ", ".join(html.escape(s["title"]) for s in unscored[:80]) + ("…" if len(unscored) > 80 else "") + "</p>")
    report = os.path.join(DATA, "report.html")
    open(report, "w", encoding="utf-8").write("\n".join(parts))
    print(" | ".join(f"{t.split(':')[0]}: {len(plan['tiers'][k])}" for k, t, _ in TIERS) + f" | unscored: {len(unscored)}")
    print(f"report: {report}")


if __name__ == "__main__":
    main()
