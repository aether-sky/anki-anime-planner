"""Filename parsing must never hang and must name the show, not the episode."""
import os, sys, time, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import scan_disk


class ParseTests(unittest.TestCase):
    def test_dangling_dash_returns_within_timeout(self):
        # anitopy loops forever on this shape; the guard must hand back a result quickly.
        started = time.time()
        title, season, episode = scan_disk.parse("Violet Evergarden - S01E07 -.mkv")
        self.assertLess(time.time() - started, 5)
        self.assertEqual(title, "Violet Evergarden")
        self.assertEqual((season, episode), (1, 7))

    def test_release_junk_is_stripped(self):
        title, season, _ = scan_disk.parse("Girls Band Cry - AV1")
        self.assertEqual(title, "Girls Band Cry")

    def test_ordinal_season_in_folder_name(self):
        title, season, _ = scan_disk.parse("Oshi no Ko 2nd Season")
        self.assertEqual((title, season), ("Oshi no Ko", 2))

    def test_episode_title_file_takes_show_from_folder(self):
        root = os.path.join("Y:", "x")
        path = os.path.join(root, "beelzebub", "01 - Boy Meets Fluffy Girl.mkv")
        title, _, episode = scan_disk.show_title(path, root)
        self.assertEqual(title.lower(), "beelzebub")
        self.assertEqual(episode, 1)

    def test_season_folder_is_skipped_for_the_show_folder(self):
        root = os.path.join("Y:", "x")
        path = os.path.join(root, "Hotel Hell", "Season 2", "Hotel Hell S02E03.mkv")
        title, season, _ = scan_disk.show_title(path, root)
        self.assertEqual((title, season), ("Hotel Hell", 2))


if __name__ == "__main__":
    unittest.main()
