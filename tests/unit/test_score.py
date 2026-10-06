"""The two-cut window fit must find both cuts when both exist and report none when the
data never reaches the hard side."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import numpy as np
import score


class FitCutsTests(unittest.TestCase):
    def test_u_shaped_suspensions_give_two_cuts(self):
        rng = np.random.default_rng(0)
        z = rng.uniform(-4, 6, 600)
        suspended = (z < -1) | (z > 4)
        low, high = score.fit_cuts(z, suspended)
        self.assertAlmostEqual(low, -1, delta=0.5)
        self.assertAlmostEqual(high, 4, delta=0.5)

    def test_only_known_side_leaves_high_cut_unfound(self):
        rng = np.random.default_rng(1)
        z = rng.uniform(-4, 3, 400)
        suspended = z < 0
        low, high = score.fit_cuts(z, suspended)
        self.assertAlmostEqual(low, 0, delta=0.5)
        self.assertIsNone(high)

    def test_clean_strips_caption_decorations(self):
        self.assertEqual(score.clean("{\\an8}（フリーレン）凱旋(がいせん)です"), "凱旋です")
        self.assertEqual(score.clean("《エリス：15歳の誕生日》"), "15歳の誕生日")


if __name__ == "__main__":
    unittest.main()
