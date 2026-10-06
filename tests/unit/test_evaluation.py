"""The kept-card frontier and the known-vocabulary rule, as the user specified them."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import score


def card(cid, text, due, suspended=False, interval=0, type_=0, deck="Show::S01E01"):
    return {"card_id": cid, "text": text, "due": due, "suspended": suspended, "interval": interval, "type": type_,
            "deck": deck, "tags": [], "reps": 0, "lapses": 0}


class FrontierTests(unittest.TestCase):
    def test_suspended_cards_after_the_last_kept_card_are_unevaluated(self):
        cards = [card(1, "一つ目", 0, suspended=True), card(2, "二つ目", 1), card(3, "三つ目", 2, suspended=True),
                 card(4, "四つ目", 3, suspended=True)]            # 3 and 4 were bulk-suspended past where the user got
        score.mark_evaluated(cards)
        self.assertEqual([c["evaluated"] for c in cards], [True, True, False, False])

    def test_order_is_new_card_position_not_id(self):
        # A rebuilt deck appended card 9 with a high id but an early position.
        cards = [card(1, "a", 0), card(2, "b", 5, suspended=True), card(9, "c", 1)]
        score.mark_evaluated(cards)
        self.assertEqual({c["card_id"]: c["evaluated"] for c in cards}, {1: True, 9: True, 2: False})

    def test_studied_cards_are_always_evaluated(self):
        cards = [card(1, "a", 0), card(2, "b", 900, suspended=False, interval=30, type_=2)]
        score.mark_evaluated(cards)
        self.assertTrue(all(c["evaluated"] for c in cards))


class VocabularyTests(unittest.TestCase):
    def test_only_easy_suspended_and_learned_cards_contribute(self):
        cards = [card(1, "魔力探知", 0, suspended=True), card(2, "勇者一行の凱旋", 1), card(3, "処刑", 2, interval=40, type_=2),
                 card(4, "賢者の墓所", 3, suspended=True), card(5, "蘇生", 4, suspended=True)]
        for c in cards:
            c["evaluated"] = True
        toks = {c["card_id"]: score.tokenize(c["text"]) for c in cards}
        card_z = {1: 0.0, 4: 9.0, 5: 1.0}                          # card 4 is above the ceiling: suspended as too hard
        words, n_learned, n_easy = score.vocabulary(cards, toks, card_z, cut_high=5.0)
        self.assertIn("魔力", words)            # easy-suspended
        self.assertIn("処刑", words)            # learned
        self.assertIn("蘇生", words)            # easy-suspended, below the ceiling
        self.assertNotIn("勇者", words)         # kept, still studying
        self.assertNotIn("賢者", words)         # suspended as too hard
        self.assertEqual((n_learned, n_easy), (1, 2))

    def test_unevaluated_suspensions_add_nothing(self):
        cards = [card(1, "魔力探知", 0, suspended=True)]
        cards[0]["evaluated"] = False
        words, _, n_easy = score.vocabulary(cards, {1: score.tokenize("魔力探知")}, {1: 0.0}, cut_high=5.0)
        self.assertEqual((words, n_easy), (set(), 0))


if __name__ == "__main__":
    unittest.main()
