---
name: anki-anime-planner
description: Rank the user's anime (MAL list + what is on disk) by how well each show's Japanese fits their current level, estimated from which Anki sentence cards they suspend, and produce a tiered learning plan with decks to mine next.
---

# Anime planner

Deterministic scripts do the collecting and scoring; you do the judgement calls:
fixing title mismatches, reading the plan back to the user, and building decks when asked.
Nothing here writes to Anki. Data lives in `~/.anki-anime-planner/` (config, cache, plan, report).

## Setup the user needs (and nothing more)

- `pip install -r requirements.txt` and ffmpeg on PATH (or `"ffmpeg"` in config).
- A jimaku API key in `~/.anki-anime-planner/config.json` as `"jimaku_api_key"`: they log in at
  jimaku.cc, open their account page, create a key. Every script that needs it stops with that
  instruction when it is missing. Ask for the key once; never guess or search for one.
- Their MAL username, passed to `run.py`. Everything else has a default: all local drives are
  scanned (with a built-in skip list), three episodes per show, thresholds as tuned below.
- Optional: AnkiConnect (add-on code 2055492159) so their cards can be read.

## Run order

`python run.py MAL_USERNAME` runs the whole chain from `scripts/`; `--rescan` ignores the directory
cache. The first run fetches ~500 shows' subtitles and takes a while; run it in the background.
The steps, each cached so a re-run after new Anki activity is quick:

1. `collect_mal.py` – public MAL list → `cache/mal.json`.
2. `scan_disk.py` – video files under `scan_roots` (default: every local drive, ~8 s per 4 TB),
   minus built-in and configured `skip_dirs`, `scan_depth` levels deep; local sub packs →
   `cache/disk.json`. Listings are cached by mtime in `cache/dirlist.json`. Filename parsing is
   guarded against anitopy hanging; a "hung on" line in stderr is informational.
3. `match.py` – MAL + disk + AniList ids + jimaku (`jimaku.py`, API, cached per lookup) →
   `cache/matches.json`. Read `matches.json["unmatched_disk"]`, ignore non-anime, put real misses
   in `config.json` `title_overrides` as `{"disk title": mal_id}`, re-run.
4. `collect_anki.py` – needs Anki open with AnkiConnect. Optional; the plan is provisional without it.
5. `fetch_subs.py` – up to `episodes_per_show` Japanese sub files per show, local pack first.
6. `score.py` – tokenizes every line (cached under `cache/tokens/`), fits the learner window from
   their cards, writes `cache/scores.json`.
7. `plan.py` – tiers → `~/.anki-anime-planner/plan.json` and `report.html`.

Tests: `python -m unittest discover -s tests/unit` from the skill folder.

## How the level is estimated

- Lines under 10 kana/kanji are trivial for everyone; they are never evidence of difficulty.
- Every non-trivial line gets a difficulty score z from weighted features: character count,
  rarest-word rank, rare-word count, predicate count, verb/auxiliary chain length, contractions,
  classical forms, keigo, characters per second, background-line flag. Rare words that repeat
  5+ times within a show are discounted. Features are standardised over the whole sub corpus.
- Suspensions are read without any flags or tags, because most of a user's history predates the
  tool. People suspend both what they already know (low z) and what is too hard (high z), so the
  window is two cuts on z: suspension probability is high below the low cut, low between, and
  rises again above the high cut. `score.py` fits both by likelihood on the user's cards.
- Only triaged episodes count: an episode whose cards are under 20 % suspended has not been gone
  through yet, and its kept cards mean nothing. Episode comes from the `S01E01`-style tag.
- If suspensions never rise again within the user's data, the high cut is reported as not found
  and nothing is marked too hard. Say that plainly; it means they should mine something harder.
- Per show: `easy_share` (below the low cut), `hard_share` (above the high cut, 0 while not found).
- To the user, the low cut is their **floor** (where they stop suspending lines as already known)
  and the high cut is their **ceiling** (where they start suspending lines as too hard). Use those
  words in chat and in the report; "cut" is the code's name for them.

## Tiers (plan.py)

easy = over 85 % of lines known (this learner suspends about two thirds of any episode as known,
so a lower bar emptied every tier) · tier3 = over 40 % too hard · tier1 = otherwise in range and
on disk · tier2 = in range, on MAL, not on disk · rewatch = completed and in or just above range.
Within a tier, the user's own MAL score orders first, then the MAL average, then the share of
lines in range. The thresholds are the constants at the top of plan.py.

## What you do with the result

- Open `report.html` for the user or summarise the top of tier 1 and 2 in chat.
- When they pick a show on disk, build the deck with `scripts/build_deck.py` (the subs2srs
  builder; see its docstring; Japanese subs come from the show's `cache/subs/<key>/` folder or a
  better BD-timed file from jimaku, English from the MKV's own track). jimaku files named
  "with furigana" need `scripts/flatten_furigana.py` first.
- If the model is provisional, say so, and ask them to install AnkiConnect so it can calibrate.
- The window is noisy until a few hundred hand decisions exist; say "low confidence" rather than
  pretending.

## Building a deck: what bit us, and the values we landed on

Run: `python build_deck.py VIDEO JA.ass EN.ass OUT.apkg --deck "Show::S01E01" --audio 0:N [--episode S01E01]`.
Use `--dry-run` first and read the line list. Probe the MKV with ffprobe to find the Japanese audio
stream (`--audio`) and the English dialogue subtitle track (extract it with `ffmpeg -map 0:N -c copy`).
ffmpeg comes from config.json `"ffmpeg"` (a path or its bin folder) or from PATH. The build's temp
folder is removed when it finishes. `score.py` caches tokenized subs under `cache/tokens/`, so a
re-fit after new Anki activity takes seconds; the first run is about a minute.

- **Card IDs are keyed to the original cue time**, so a rebuilt deck updates cards in place when
  re-imported. Keep it that way; do not key on retimed times or text.
- **Suspended cards do not survive import** in the user's Anki, so the builder does not try. Lines
  under `MIN_CHARS` = 8 kana/kanji get a `short` tag; tell them to suspend by tag after importing.
- **Clip edges** (constants at the top of build_deck.py): `START_TRIM` 0.05 s, `END_PAD` 0.15 s,
  `NEIGHBOR_GAP` 0.02 s. History: 80 ms trims clipped final vowels ("…終わって" lost たよね); 0 pad
  on a show whose captions end tight (Mushoku Tensei) clipped the last か, the English cues ran
  150 ms longer, hence the pad. The neighbour clamp only looks at lines in the same screen
  position; a background (top) line spoken over the main line must not shorten it.
- **Audio**: cut from the source track with `-c copy`. Re-encoding AAC to mp3 was audibly worse
  (a copy of a copy). A lossless source (FLAC) gets one mp3 pass at `-q:a 0`. A copy cut rounds
  down to the last whole audio frame (~20 ms), which is why `END_TRIM` is gone.
- **Retiming**: `retime()` follows the English track with a rolling median and handles drift and
  steps up to ~1 s (Frieren ep 4 had a stepped 0.3 s offset). It does **not** find a big constant
  offset. When subs were timed to a different cut (Lain: opening before the cold open, 120 s off),
  grid-search a constant shift against the English cue starts first, apply it with pysubs2
  `shift()`, and check the residual is within ±100 ms before building.
- **Which Japanese file**: on jimaku prefer BD-timed groups (Moozzi2, Beatrice) for BD encodes;
  AT-X broadcast captions have ad-break steps and may bundle two episodes. Files named
  "with furigana" are one positioned event per word: run `flatten_furigana.py` first. Files
  marked "bad transcription" are auto-transcribed; spot-check the opening lines against the
  English before trusting them. Some files are UTF-16: decode and rewrite as UTF-8.
- **Caption quirks handled by `clean_ja`/`load_ja`**: （speaker）and（SFX）stripped, furigana in
  ascii parens stripped, ♪ lines dropped, closed-caption re-emits of the same line merged,
  `{\an8}` marks a background line (pair only with the English "Top-Alt"/"Main - Top" style).
- **Cues past the end of the video** (ED lyrics after a shift) are dropped; otherwise ffmpeg
  produces no thumbnail and the package write fails midway.
- **Fonts**: the card CSS asks for Noto Sans JP / Yu Gothic; without them Chrome falls back to a
  Chinese font. Tell the user to set Yu Gothic UI or Meiryo in the note type if kanji look off.
- **Card layout the user settled on**: front = thumbnail + audio only; back = thumbnail, Japanese,
  two context lines either side, no audio replay, no English anywhere (English stays in a hidden
  Meaning field). Don't reintroduce English or Japanese-on-front without being asked.
