"""Vocabulary features: stray single kana are not words, and unknown words raise the score."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import score


class ContentLemmaTests(unittest.TestCase):
    def test_lone_kana_tokens_are_dropped(self):
        toks = [("ん", "名詞", "普通名詞", "*"), ("っ", "名詞", "普通名詞", "*"), ("ー", "名詞", "普通名詞", "*"),
                ("魔力", "名詞", "普通名詞", "*"), ("木", "名詞", "普通名詞", "*"), ("走る", "動詞", "一般", "*")]
        self.assertEqual(score.content_lemmas(toks), ["魔力", "木", "走る"])

    def test_unknown_words_count_only_when_a_vocabulary_is_given(self):
        toks = score.tokenize("魔力探知にほとんど引っかからない")
        rank = {"魔力": 2500, "探知": 9000, "引っ掛かる": 4000, "ほとんど": 300}
        with_vocab = score.features("魔力探知にほとんど引っかからない", 3.0, False, toks, rank, {}, 1000, {"魔力", "ほとんど"})
        without = score.features("魔力探知にほとんど引っかからない", 3.0, False, toks, rank, {}, 1000, None)
        n_unknown = score.FEATURES.index("n_unknown")
        self.assertGreater(with_vocab[n_unknown], 0)
        self.assertEqual(without[n_unknown], 0)


if __name__ == "__main__":
    unittest.main()
