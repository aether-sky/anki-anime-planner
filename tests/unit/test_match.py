"""Title matching must be deterministic and must not choke on an entry reachable by two names."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import match


class BestMatchTests(unittest.TestCase):
    def test_entry_reachable_by_romaji_and_english_name_matches_once(self):
        entries = [{"mal_id": 1, "title": "Tengoku Daimakyou", "title_eng": "Heavenly Delusion"},
                   {"mal_id": 2, "title": "Heavenly Delusion Movie", "title_eng": "Heavenly Delusion Movie"}]
        index = match.build_index(entries, ("title", "title_eng"))
        e, how = match.best_match({"title": "Heavenly Delusion", "season": 1}, index, "title", 0.8)
        self.assertEqual(e["mal_id"], 1)

    def test_season_in_folder_picks_the_sequel(self):
        entries = [{"mal_id": 1, "title": "Goblin Slayer", "title_eng": ""}, {"mal_id": 2, "title": "Goblin Slayer II", "title_eng": ""}]
        index = match.build_index(entries, ("title", "title_eng"))
        e, _ = match.best_match({"title": "Goblin Slayer", "season": 2}, index, "title", 0.8)
        self.assertEqual(e["mal_id"], 2)

    def test_tie_is_broken_by_id_not_memory_address(self):
        entries = [{"mal_id": 20, "title": "Same Name", "title_eng": ""}, {"mal_id": 10, "title": "Same Name", "title_eng": ""}]
        index = match.build_index(entries, ("title", "title_eng"))
        picks = {match.best_match({"title": "Same Name", "season": 1}, index, "title", 0.8)[0]["mal_id"] for _ in range(5)}
        self.assertEqual(picks, {20})


if __name__ == "__main__":
    unittest.main()
