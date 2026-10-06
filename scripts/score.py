"""Score every subtitle line for difficulty and fit the learner's window from Anki.

Lines under TRIVIAL_CHARS kana/kanji are trivial regardless of content. Longer lines get
a difficulty score z from weighted features: how many of the line's words the learner does
not know and how rare those are, general vocabulary rarity, clause structure, register,
speed. The learner knows a word when it is on a card they suspended because it was easy (a
suspended card that is not above their ceiling) or on a card they have learned (kept, with
an interval of LEARNED_MIN_INTERVAL days or more).

The window is two cuts on z, fitted from which cards the learner suspended: below the floor
they usually suspend, between the cuts they keep, above the ceiling they suspend again
because lines are too hard. Only evaluated cards count: an episode must have enough
suspensions, and within it only cards up to the last one the learner kept, since later
suspensions come from bulk actions. Because "easy" depends on the ceiling and the ceiling
on the scores, the fit runs two rounds. When nothing evaluated was hard enough for
suspensions to rise again, the ceiling is reported as not found. Writes cache/scores.json.
"""
import collections, math, os, re
import numpy as np
import fugashi, pysubs2
from common import CACHE, SUBS, load_json, save_json, log

TOKENS = os.path.join(CACHE, "tokens")
os.makedirs(TOKENS, exist_ok=True)

TRIVIAL_CHARS = 10
EVALUATED_MIN_RATE = 0.2       # an episode counts as evaluated once this share of its cards is suspended
MIN_EVALUATED_CARDS = 60
LEARNED_MIN_INTERVAL = 21      # days; a kept card with at least this interval counts as learned
REPEAT_RATE = 0.005            # a word seen at least this often per line of a show is learnable in context
JA = re.compile(r"[ぁ-ゖァ-ヺー一-鿿々〆ヵヶ]")
KANJI = re.compile(r"[一-鿿々]")
CONTENT_POS = {"名詞", "動詞", "形容詞", "副詞", "形状詞", "代名詞", "連体詞", "接続詞"}
SKIP_POS2 = {"数詞", "固有名詞"}
CONTRACTION = re.compile(r"てん|ねえ|ねぇ|ちゃ|じゃ(?!ない)|っす|やが|んの|とく|ってば|ねー|かよ|だろ\b|やん|ちまう|てえ|なきゃ|ぜ$|ぞ$|っつ")
CLASSICAL = re.compile(r"たる|べし|べき|ざる|せよ|まい|ごとし|なり$|ぬ$|おる|ござ|しかる|ゆえ|いかん|ぬか")
KEIGO = re.compile(r"ございま|なさ|いただ|くださ|おっしゃ|いらっしゃ|申し|致し|いたし|ご覧|お[ぁ-ゖ一-鿿]{1,3}(になる|する|です|ください)|でございます")
FEATURES = ["chars", "n_unknown", "unknown_rarest_log", "rarest_log", "n_rare", "n_pred", "max_chain", "contractions", "classical", "keigo", "cps", "top"]
WEIGHTS = np.array([0.8, 1.2, 0.8, 0.6, 0.5, 0.5, 0.3, 0.4, 0.5, 0.3, 0.3, 0.2])
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


def content_lemmas(toks):
    """Content words of a line. A lone kana (ん, っ, ー and friends) tagged as a noun is a
    segmentation slip, not a word, and would otherwise count as an ultra-rare unknown."""
    return [l for l, p1, p2, _ in toks
            if p1 in CONTENT_POS and p2 not in SKIP_POS2 and not (len(l) == 1 and not KANJI.search(l))]


def features(text, duration, top, toks, rank, show_counts, show_lines, known):
    """known is the learner's vocabulary (a set of lemmas) or None when no cards are available."""
    chars = len(JA.findall(text))
    content = content_lemmas(toks)
    ranks, unknown_ranks = [], []
    for lemma in content:
        r = rank.get(lemma, len(rank) + 1)
        if show_counts.get(lemma, 0) >= REPEAT_RATE * show_lines:
            r = min(r, 3000)
        ranks.append(r)
        if known is not None and lemma not in known:
            unknown_ranks.append(r)
    rarest = max(ranks) if ranks else 1
    n_rare = sum(r > 3000 for r in ranks)
    n_unknown = len(unknown_ranks)
    unknown_rarest_log = math.log10(max(unknown_ranks)) if unknown_ranks else 0.0
    n_pred = sum(1 for t in toks if t[1] in ("動詞", "形容詞"))
    chain = best = 0
    for t in toks:
        chain = chain + 1 if t[1] in ("動詞", "形容詞", "助動詞", "接尾辞") else 0
        best = max(best, chain)
    return [chars, n_unknown, unknown_rarest_log, math.log10(rarest), n_rare, n_pred, best,
            len(CONTRACTION.findall(text)), len(CLASSICAL.findall(text)), len(KEIGO.findall(text)),
            chars / duration, int(top)]


def fit_cuts(z, suspended):
    """Two cuts on the difficulty scale. Suspension probability is sigma(low - z) + sigma(z - high):
    high near the bottom (easy), low in the middle (kept), rising again past the ceiling (too hard).
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


def episode_of(card):
    """(show, episode) for a card. Decks from this skill carry show and S01E01 tags; decks
    from other tools usually have neither, so the deck name stands in."""
    ep = next((t for t in card["tags"] if EPISODE_TAG.match(t)), "")
    show = next((t for t in card["tags"] if not EPISODE_TAG.match(t) and t != "short"), "")
    if not ep:
        parts = card["deck"].split("::")
        show, ep = (show or parts[0]), (parts[-1] if len(parts) > 1 else card["deck"])
    return show, ep


def mark_evaluated(cards):
    """Set card["evaluated"]. The learner works through a deck in order, so the last card
    they kept marks how far they got; a new card beyond it that is suspended came from a
    bulk action (the "short" tag), not a decision. Order is the new-card position (due of
    an unstudied card); a card that has been studied is evaluated by definition."""
    by_episode = collections.defaultdict(list)
    for c in cards:
        by_episode[episode_of(c)].append(c)
    for cs in by_episode.values():
        def position(c):
            return c["due"] if c.get("type", 0) == 0 else -1          # studied cards sort before every new card
        kept_new = [position(c) for c in cs if not c["suspended"] and c.get("type", 0) == 0]
        frontier = max(kept_new) if kept_new else max(position(c) for c in cs)
        for c in cs:
            c["evaluated"] = position(c) <= frontier
    return by_episode


def vocabulary(cards, card_toks, card_z=None, cut_high=None):
    """Lemmas the learner knows: words on evaluated cards they suspended because they were easy
    (not above the ceiling) and on cards they have learned. Before any ceiling exists, only
    suspended trivial cards count as easy."""
    learned = [c for c in cards if not c["suspended"] and c["interval"] >= LEARNED_MIN_INTERVAL]
    if card_z is None:
        easy = [c for c in cards if c["suspended"] and c["evaluated"] and len(JA.findall(clean(c["text"]))) < TRIVIAL_CHARS]
    else:
        easy = [c for c in cards if c["suspended"] and c["evaluated"]
                and (c["card_id"] not in card_z or cut_high is None or card_z[c["card_id"]] <= cut_high)]
    words = {l for c in learned + easy for l in content_lemmas(card_toks[c["card_id"]])}
    return words, len(learned), len(easy)


def main():
    shows = load_json(os.path.join(CACHE, "matches.json"))["shows"]
    anki = load_json(os.path.join(CACHE, "anki.json"))
    cards = anki["cards"] if anki and anki.get("cards") else []       # an empty collection is the same as none

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
            freq.update(content_lemmas(tk))
    rank = {lemma: i + 1 for i, (lemma, _) in enumerate(freq.most_common())}
    log(f"{len(corpus)} shows, {sum(len(v[0]) for v in corpus.values())} lines, {len(rank)} distinct words")

    card_toks = {c["card_id"]: tokenize(clean(c["text"])) for c in cards}
    by_episode = mark_evaluated(cards)
    for c in cards:
        c["episode"] = episode_of(c)
    # A deck is a sample of its show, so the in-show repetition discount uses counts over
    # all the learner's cards from that show, at the same per-line rate as the corpus.
    show_counts_by_tag, show_lines_by_tag = {}, collections.Counter()
    for (show, ep), cs in by_episode.items():
        counts = show_counts_by_tag.setdefault(show, collections.Counter())
        for c in cs:
            counts.update(content_lemmas(card_toks[c["card_id"]]))
        show_lines_by_tag[show] += len(cs)

    known, n_learned, n_easy = vocabulary(cards, card_toks) if cards else (None, 0, 0)
    rounds = 2 if cards else 1
    for round_ in range(rounds):
        # pass 2: features for every non-trivial line, standardised over the corpus; per-show vocabulary coverage
        rows, index, vocab = [], [], {}
        for key, (lines, toks) in corpus.items():
            show_counts = collections.Counter(l for tk in toks for l in content_lemmas(tk))
            if known is not None:
                tokens = sum(show_counts.values())
                covered = sum(n for l, n in show_counts.items() if l in known)
                vocab[key] = {"coverage": round(covered / tokens, 3) if tokens else None,
                              "new_words": sum(1 for l in show_counts if l not in known)}
            for (text, dur, top), tk in zip(lines, toks):
                if len(JA.findall(text)) < TRIVIAL_CHARS:
                    index.append((key, True)); rows.append(None); continue
                index.append((key, False)); rows.append(features(text, dur, top, tk, rank, show_counts, len(lines), known))
        X_all = np.array([r for r in rows if r], dtype=float)
        mu, sd = X_all.mean(0), X_all.std(0) + 1e-9
        z_all = ((X_all - mu) / sd) @ WEIGHTS

        cut_low = cut_high = None
        evaluated_cards = 0
        if cards:
            # Each episode's cards are scored against the vocabulary of the other episodes: with
            # their own words in, every card looks fully known and the floor floats up the scale.
            card_z = {}
            for (show, ep), cs in by_episode.items():
                known_elsewhere = {l for c in cards if c["episode"] != (show, ep) for l in content_lemmas(card_toks[c["card_id"]])} & known
                for c in cs:
                    text = clean(c["text"])
                    if len(JA.findall(text)) < TRIVIAL_CHARS:
                        continue
                    f = np.array(features(text, 3.0, False, card_toks[c["card_id"]], rank, show_counts_by_tag[show], show_lines_by_tag[show], known_elsewhere), dtype=float)
                    for name in ("cps", "top"):                      # cards carry no timing or screen position
                        f[FEATURES.index(name)] = mu[FEATURES.index(name)]
                    card_z[c["card_id"]] = float(((f - mu) / sd) @ WEIGHTS)
            zs, ys = [], []
            for (show, ep), cs in by_episode.items():
                seen = [c for c in cs if c["evaluated"]]
                rate = sum(c["suspended"] for c in seen) / len(seen)
                if rate < EVALUATED_MIN_RATE:
                    if round_ == 0:
                        log(f"  {show} {ep}: {len(cs)} cards, {rate:.0%} suspended, not evaluated yet")
                    continue
                for c in seen:
                    if c["card_id"] in card_z:
                        zs.append(card_z[c["card_id"]]); ys.append(c["suspended"])
                if round_ == 0:
                    log(f"  {show} {ep}: {len(seen)} of {len(cs)} cards evaluated, {rate:.0%} of those suspended, used")
            evaluated_cards = len(zs)
            if evaluated_cards >= MIN_EVALUATED_CARDS and 0 < sum(ys) < len(ys):
                cut_low, cut_high = fit_cuts(zs, ys)
                zs = np.array(zs)
                log(f"round {round_ + 1}: vocabulary {len(known)} words; floor z={cut_low:+.2f} ({(zs < cut_low).mean():.0%} of evaluated cards below), "
                    + (f"ceiling z={cut_high:+.2f} ({(zs > cut_high).mean():.0%} above)" if cut_high is not None
                       else "ceiling not found: nothing evaluated was hard enough"))
            elif evaluated_cards >= MIN_EVALUATED_CARDS:
                log("every evaluated card is on one side (all suspended or none); the window cannot be placed")
            else:
                log(f"only {evaluated_cards} evaluated long cards; need {MIN_EVALUATED_CARDS}")
            if round_ < rounds - 1:                                  # the last round's scores and vocabulary stay consistent
                known, n_learned, n_easy = vocabulary(cards, card_toks, card_z, cut_high)

    model = {"features": FEATURES, "weights": WEIGHTS.tolist(), "mu": mu.tolist(), "sd": sd.tolist(),
             "vocabulary": len(known) if known is not None else 0, "learned_cards": n_learned, "easy_cards": n_easy}
    if cut_low is None:
        cut_low = float(np.quantile(z_all, 0.3)); cut_high = float(np.quantile(z_all, 0.8))
        model.update({"provisional": True, "fitted_on": evaluated_cards})
    else:
        model.update({"provisional": False, "fitted_on": evaluated_cards})
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
        easy_share = float((zs < cut_low).mean()) if len(zs) else None
        hard = float((zs > cut_high).mean()) if len(zs) and cut_high is not None else (0.0 if len(zs) else None)
        out[key] = {"lines": n, "trivial_share": round(1 - len(zs) / n, 3),
                    "easy_share": round(easy_share, 3) if easy_share is not None else None,
                    "hard_share": round(hard, 3) if hard is not None else None,
                    "mean_z": round(float(zs.mean()), 3) if len(zs) else None, "hist": hist.tolist(),
                    **vocab.get(key, {"coverage": None, "new_words": None})}
    save_json(os.path.join(CACHE, "scores.json"), {"model": model, "shows": out})
    print(f"scored {len(out)} shows; window {'fitted on %d evaluated cards' % evaluated_cards if not model['provisional'] else 'PROVISIONAL'}"
          + ("; ceiling not found yet" if cut_high is None else "")
          + (f"; vocabulary {model['vocabulary']} known words" if cards else ""))


if __name__ == "__main__":
    main()
