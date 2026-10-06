# anime-planner

A Claude Code skill that ranks the anime you own and the anime on your MyAnimeList by how
well their Japanese fits your current level, then builds subs2srs-style Anki decks for the
ones worth mining. Your level is read from your existing Anki sentence cards: what you
suspend as already known, and what you suspend as too hard. No flags, no tagging ritual.

## Install

1. Copy this folder to `~/.claude/skills/anime-planner` (Claude Code picks it up next session).
2. `pip install -r requirements.txt`
3. Have `ffmpeg` on your PATH (or set `"ffmpeg"` in the config later).
4. Get a jimaku.cc API key: log in, open your account page, create a key. The first run
   tells you where to put it.
5. Optional: the AnkiConnect add-on (code 2055492159) in Anki, so your cards can be read.
   Without it the plan is provisional.

## Use

Ask Claude for a plan, or run it yourself:

    cd ~/.claude/skills/anime-planner/scripts
    python run.py YOUR_MAL_USERNAME

That scans every local drive for video files (about 8 s per 4 TB), fetches three episodes
of Japanese subtitles per show, scores every line, and writes `~/.anime-planner/report.html`.
Everything else has a default; see `~/.anime-planner/config.json` after the first run if you
want to narrow the scan, point at a local subtitle pack, or change the thresholds.

Then ask Claude to build a deck for anything in tier 1. Import the `.apkg`, search `tag:short`
in the browser and suspend those, and study. Suspend what you already know as you go; the
next run reads those decisions and moves your window.

## What it reads and writes

Reads: your public MAL list, AniList (ids only), jimaku (subtitle files), your drives
(file names and sizes only), and Anki over AnkiConnect (read only). Writes: only
`~/.anime-planner/` and the `.apkg` files you ask for. Nothing is written to Anki.

## Tests

    python -m unittest discover -s tests/unit
