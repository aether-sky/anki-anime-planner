"""Subtitle file selection: one file per episode, BD groups first, ranges and other-language files skipped."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import fetch_subs


class PickTests(unittest.TestCase):
    def test_one_file_per_episode_preferring_bd(self):
        names = ["[AT-X] Show - 01.srt", "[Moozzi2] Show - 01 (BD 1080p).ass", "[Moozzi2] Show - 02 (BD 1080p).ass",
                 "[AT-X] Show - 02.srt", "[AT-X] Show - 03.srt"]
        self.assertEqual(fetch_subs.pick(names, 3),
                         ["[Moozzi2] Show - 01 (BD 1080p).ass", "[Moozzi2] Show - 02 (BD 1080p).ass", "[AT-X] Show - 03.srt"])

    def test_episode_ranges_are_not_treated_as_an_episode(self):
        self.assertIsNone(fetch_subs.episode_of("[NanakoRaws] Show S03E01-02 (AT-X).srt"))
        self.assertEqual(fetch_subs.episode_of("[Judas] Show - S03E04 [1080p].srt"), 4)

    def test_other_language_and_furigana_files_are_rejected(self):
        names = ["[SubsPlease] Show - 01 [F02B9CEE]_ja-en.ass", "Show [CHS, JPN].ass",
                 "Show S03E01 with furigana - title.ja.ass", "Show - 01.sup.7z", "Show - 01.srt"]
        self.assertEqual(fetch_subs.usable(names), ["Show - 01.srt"])


if __name__ == "__main__":
    unittest.main()
