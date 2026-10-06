"""Score every subtitle line for difficulty and fit the learner's window from Anki.

Lines under TRIVIAL_CHARS kana/kanji are trivial regardless of content. Longer lines
get a difficulty score z from weighted features (vocabulary rarity, clause structure,
register, speed). The learner's window is two cuts on that scale, fitted from which of
their cards they suspended: below the low cut they suspend as already known, above the
high cut they suspend as too hard, in between they keep. Only episodes the learner has
actually triaged (enough suspensions) are used. When nothing they triaged was hard
enough for suspensions to rise again, the high cut is reported as not found rather
than guessed. Writes cache/scores.json.
"""
import collections, math, os, re
import numpy as np
import fugashi, pysubs2
from common import CACHE, SUBS, load_json, save_json, log

TOKENS = os.path.join(CACHE, "tokens")
os.makedirs(TOKENS, exist_ok=True)

TRIVIAL_CHARS = 10
TRIAGED_MIN_RATE = 0.2         # an episode counts as triaged once this share of its cards is suspended
MIN_TRIAGED_CARDS = 60
JA = re.compile(r"[ぁ-ゖァ-ヺー一-鿿々〆ヵヶ]")
CONTENT_POS = {"名詞", "動詞", "形容詞", "副詞", "形状詞", "代名詞", "連体詞", "接続詞"}
SKIP_POS2 = {"数詞", "固有名詞"}
CONTRACTION = re.compile(r"てん|ねえ|ねぇ|ちゃ|じゃ(?!ない)|っす|やが|んの|とく|ってば|ねー|かよ|だろ\b|やん|ちまう|てえ|なきゃ|ぜ$|ぞ$|っつ")
CLASSICAL = re.compile(r"たる|べし|べき|ざる|せよ|まい|ごとし|なり$|ぬ$|おる|ござ|しかる|ゆえ|いかん|ぬか")
KEIGO = re.compile(r"ございま|なさ|いただ|くださ|おっしゃ|いらっしゃ|申し|致し|いたし|ご覧|お[ぁ-ゖ一-鿿]{1,3}(になる|する|です|ください)|でございます")
FEATURES = ["chars", "rarest_log", "n_rare", "n_pred", "max_chain", "contractions", "classical", "keigo", "cps", "top"]
WEIGHTS = np.array([0.8, 1.0, 0.8, 0.5, 0.3, 0.4, 0.5, 0.3, 0.3, 0.2])
EPISODE_TAG = re.compile(r"^S\d+E\d+$", re.I)

tagger = fugashi.Tagger()


def clean(text):
    t = re.sub(r"\{[^}]*\}", "", text).replace("\\N", "").replace("\\n", "").replace("\\h", " ")
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\(([ぁ-ゖァ-ヺー]+)\)", "", t)                 # furigana in ascii parens
    t = re.sub(r"[（(][^）)]*[）)]", "", t)                       # speaker names, sound effects
    t = re.sub(r"[《〈]([^：:》〉]*[：:])?", "", t).replace("》", "").replace("〉", "")
    t = re.sub(r"^[^：:\s]{1,8}[：:]", "", t)                   # "name：line"
    return t.strip()


def load_lines(folder):
    lines = []
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith((".srt", ".ass", ".ssa")):
            continue
        try:
            subs = pysubs2.load(os.path.join(folder, f))
        except Exception as e:
            log(f"{folder}/{f}: unreadable ({e})"); continue
        for e in subs:
            if "♪" in e.text or e.is_comment:
                continue
            top = "\\an8" in e.text or "top" in e.style.lower()
            t = clean(e.text)
            if JA.search(t):
                lines.append((t, max(0.3, (e.end - e.start) / 1000), top))
    return lines


def tokenize(text):
    toks = []
    for w in tagger(text):
        f = w.feature
        lemma = f.lemma if f.lemma and f.lemma != "*" else w.surface
        toks.append((lemma, f.pos1, f.pos2 or "*", f.cForm or "*"))
    return toks


REPEAT_RATE = 0.005            # a word seen at least this often per line of a show is learnable in context


def features(text, duration, top, toks, rank, show_counts, show_lines):
    chars = len(JA.findall(text))
    content = [t for t in toks if t[1] in CONTENT_POS and t[2] not in SKIP_POS2]
    ranks = []
    for lemma, *_ in content:
        r = rank.get(lemma, len(rank) + 1)
        if show_counts.get(lemma, 0) >= REPEAT_RATE * show_lines:
            r = min(r, 3000)
        ranks.append(r)
    rarest = max(ranks) if ranks else 1
    n_rare = sum(r > 3000 for r in ranks)
    n_pred = sum(1 for t in toks if t[1] in ("動詞", "形容詞"))
    chain = best = 0
    for t in toks:
        chain = chain + 1 if t[1] in ("動詞", "形容詞", "助動詞", "接尾辞") else 0
        best = max(best, chain)
    return [chars, math.log10(rarest), n_rare, n_pred, best,
            len(CONTRACTION.findall(text)), len(CLASSICAL.findall(text)), len(KEIGO.findall(text)),
            chars / duration, int(top)]


def fit_cuts(z, suspended):
    """Two cuts on the difficulty scale. Suspension probability is sigma(low - z) + sigma(z - high):
    high near the bottom (known), low in the middle (kept), rising again past the high cut (too hard).
    Grid search on the log-likelihood; the high cut may land beyond the data, meaning not found."""
    z, y = np.asarray(z), np.asarray(suspended, dtype=float)
    lo_grid = np.linspace(z.min() - 1, z.max(), 80)
    hi_grid = np.append(np.linspace(z.min(), z.max() + 1, 80), np.inf)
    best = (-np.inf, None, None)
    for low in lo_grid:
        p_low = 1 / (1 + np.exp(z - low))
        for high in hi_grid:
            if high <= low + 0.5:
                continue
            p = np.clip(p_low + (0 if np.isinf(high) else 1 / (1 + np.exp(high - z))), 1e-6, 1 - 1e-6)
            ll = float((y * np.log(p) + (1 - y) * np.log(1 - p)).sum())
            if ll > best[0]:
                best = (ll, float(low), None if np.isinf(high) else float(high))
    return best[1], best[2]


def show_tokens(key, folder):
    """Lines and tokens for one show, cached against the sub files' size and mtime."""
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith((".srt", ".ass", ".ssa")))
    sig = [[f, os.path.getsize(os.path.join(folder, f)), os.path.getmtime(os.path.join(folder, f))] for f in files]
    cache_path = os.path.join(TOKENS, f"{key}.json")
    cached = load_json(cache_path)
    if cached and cached["sig"] == sig:
        return cached["lines"], cached["toks"]
    lines = load_lines(folder)
    toks = [tokenize(t) for t, _, _ in lines]
    save_json(cache_path, {"sig": sig, "lines": lines, "toks": toks})
    return lines, toks


def main():
    shows = load_json(os.path.join(CACHE, "matches.json"))["shows"]
    anki = load_json(os.path.join(CACHE, "anki.json"))

    # pass 1: lines and tokens per show, corpus frequency
    corpus, freq = {}, collections.Counter()
    for s in shows:
        folder = os.path.join(SUBS, s["key"])
        if not os.path.exists(os.path.join(folder, "meta.json")):
            continue
        lines, toks = show_tokens(s["key"], folder)
        if len(lines) < 50:
            continue
        corpus[s["key"]] = (lines, toks)
        for tk in toks:
            freq.update(l for l, p1, p2, _ in tk if p1 in CONTENT_POS and p2 not in SKIP_POS2)
    rank = {lemma: i + 1 for i, (lemma, _) in enumerate(freq.most_common())}
    log(f"{len(corpus)} shows, {sum(len(v[0]) for v in corpus.values())} lines, {len(rank)} distinct words")

    # pass 2: features for every non-trivial line, standardised over the corpus
    rows, index = [], []
    for key, (lines, toks) in corpus.items():
        show_counts = collections.Counter(l for tk in toks for l, p1, p2, _ in tk if p1 in CONTENT_POS)
        for (text, dur, top), tk in zip(lines, toks):
            if len(JA.findall(text)) < TRIVIAL_CHARS:
                index.append((key, True)); rows.append(None); continue
            index.append((key, False)); rows.append(features(text, dur, top, tk, rank, show_counts, len(lines)))
    X_all = np.array([r for r in rows if r], dtype=float)
    mu, sd = X_all.mean(0), X_all.std(0) + 1e-9
    z_all = ((X_all - mu) / sd) @ WEIGHTS
    model = {"features": FEATURES, "weights": WEIGHTS.tolist(), "mu": mu.tolist(), "sd": sd.tolist()}

    # the learner's window from triaged episodes
    cut_low = cut_high = None
    triaged_cards = 0
    if anki:
        # Decks from this skill carry show and S01E01 tags; decks from other tools usually have
        # neither, so the deck name stands in: "Show::Episode" splits, anything else is one show.
        by_episode = collections.defaultdict(list)
        for c in anki["cards"]:
            ep = next((t for t in c["tags"] if EPISODE_TAG.match(t)), "")
            show = next((t for t in c["tags"] if not EPISODE_TAG.match(t) and t != "short"), "")
            if not ep:
                parts = c["deck"].split("::")
                show, ep = (show or parts[0]), (parts[-1] if len(parts) > 1 else c["deck"])
            by_episode[(show, ep)].append(c)
        # A deck is a sample of its show, so the in-show repetition discount uses counts over
        # all the user's cards from that show, at the same per-line rate as the corpus.
        card_toks = {c["card_id"]: tokenize(clean(c["text"])) for c in anki["cards"]}
        show_counts_by_tag, show_lines_by_tag = {}, collections.Counter()
        for (show, ep), cards in by_episode.items():
            counts = show_counts_by_tag.setdefault(show, collections.Counter())
            for c in cards:
                counts.update(l for l, p1, p2, _ in card_toks[c["card_id"]] if p1 in CONTENT_POS)
            show_lines_by_tag[show] += len(cards)
        zs, ys = [], []
        for (show, ep), cards in by_episode.items():
            rate = sum(c["suspended"] for c in cards) / len(cards)
            if rate < TRIAGED_MIN_RATE:
                log(f"  {show} {ep}: {len(cards)} cards, {rate:.0%} suspended, not triaged yet"); continue
            for c in cards:
                text = clean(c["text"])
                if len(JA.findall(text)) < TRIVIAL_CHARS:
                    continue
                f = np.array(features(text, 3.0, False, card_toks[c["card_id"]], rank, show_counts_by_tag[show], show_lines_by_tag[show]), dtype=float)
                for name in ("cps", "top"):                      # cards carry no timing or screen position
                    f[FEATURES.index(name)] = mu[FEATURES.index(name)]
                zs.append(float(((f - mu) / sd) @ WEIGHTS)); ys.append(c["suspended"])
            log(f"  {show} {ep}: {len(cards)} cards, {rate:.0%} suspended, used")
        triaged_cards = len(zs)
        if triaged_cards >= MIN_TRIAGED_CARDS and 0 < sum(ys) < len(ys):
            cut_low, cut_high = fit_cuts(zs, ys)
            zs = np.array(zs)
            log(f"window from {triaged_cards} triaged long cards: known below z={cut_low:+.2f} "
                f"({(zs < cut_low).mean():.0%} of them), too hard above "
                + (f"z={cut_high:+.2f} ({(zs > cut_high).mean():.0%} of them)" if cut_high is not None
                   else "not found: nothing triaged was hard enough"))
        elif triaged_cards >= MIN_TRIAGED_CARDS:
            log("every triaged card is on one side (all suspended or none); the window cannot be placed")
        else:
            log(f"only {triaged_cards} triaged long cards; need {MIN_TRIAGED_CARDS}")
    if cut_low is None:
        cut_low = float(np.quantile(z_all, 0.3)); cut_high = float(np.quantile(z_all, 0.8))
        model.update({"provisional": True, "fitted_on": triaged_cards})
    else:
        model.update({"provisional": False, "fitted_on": triaged_cards})
    model.update({"cut_low": cut_low, "cut_high": cut_high})

    # per show summary
    out, i = {}, 0
    for key, (lines, _) in corpus.items():
        n, zs = len(lines), []
        for _ in lines:
            _, trivial = index[i]
            if not trivial:
                zs.append(float(((np.array(rows[i]) - mu) / sd) @ WEIGHTS))
            i += 1
        zs = np.array(zs)
        hist, _ = np.histogram(np.clip(zs, -6, 6), bins=8, range=(-6, 6)) if len(zs) else (np.zeros(8), None)
        easy = float((zs < cut_low).mean()) if len(zs) else None
        hard = float((zs > cut_high).mean()) if len(zs) and cut_high is not None else (0.0 if len(zs) else None)
        out[key] = {"lines": n, "trivial_share": round(1 - len(zs) / n, 3),
                    "easy_share": round(easy, 3) if easy is not None else None,
                    "hard_share": round(hard, 3) if hard is not None else None,
                    "mean_z": round(float(zs.mean()), 3) if len(zs) else None, "hist": hist.tolist()}
    save_json(os.path.join(CACHE, "scores.json"), {"model": model, "shows": out})
    print(f"scored {len(out)} shows; window {'fitted on %d triaged cards' % triaged_cards if not model['provisional'] else 'PROVISIONAL'}"
          + ("; high cut not found yet" if cut_high is None else ""))


if __name__ == "__main__":
    main()
