"""Read sentence cards from Anki over AnkiConnect into cache/anki.json. Read only.

Every note whose model has the configured sentence field is included, with its
card state: suspended, interval, reps, lapses, ease. Nothing in Anki is modified.
"""
import os, re, sys
from common import CACHE, load_config, save_json, http_post_json, log


def call(url, action, **params):
    r = http_post_json(url, {"action": action, "version": 6, "params": params})
    if r.get("error"):
        sys.exit(f"AnkiConnect {action}: {r['error']}")
    return r["result"]


def main():
    cfg = load_config(); url = cfg["ankiconnect_url"]; field = cfg["anki_field"]
    try:
        version = call(url, "version")
    except Exception as e:
        sys.exit(f"AnkiConnect not reachable at {url} ({e}). Open Anki with the AnkiConnect add-on (code 2055492159) installed.")
    note_ids = call(url, "findNotes", query=f"{field}:_*")
    log(f"AnkiConnect v{version}: {len(note_ids)} notes with a {field} field")
    cards = []
    for i in range(0, len(note_ids), 500):
        notes = call(url, "notesInfo", notes=note_ids[i:i + 500])
        card_ids = [c for n in notes for c in n["cards"]]
        info = {c["cardId"]: c for c in call(url, "cardsInfo", cards=card_ids)}
        for n in notes:
            text = re.sub(r"<[^>]+>", "", n["fields"][field]["value"]).strip()
            for cid in n["cards"]:
                c = info[cid]
                cards.append({
                    "note_id": n["noteId"], "card_id": cid, "text": text, "deck": c["deckName"],
                    "tags": n["tags"], "suspended": c["queue"] == -1, "interval": c["interval"],
                    "reps": c["reps"], "lapses": c["lapses"], "ease": c["factor"], "due": c["due"],
                    "type": c["type"],              # 0 new (due is its position in the deck), 1 learning, 2 review
                })
    save_json(os.path.join(CACHE, "anki.json"), {"cards": cards})
    susp = sum(c["suspended"] for c in cards); reviewed = sum(c["reps"] > 0 for c in cards)
    print(f"{len(cards)} cards: {susp} suspended, {reviewed} reviewed at least once")


if __name__ == "__main__":
    main()
