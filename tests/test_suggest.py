"""Suggestions for a person naming a category (ontodag.suggest,
docs/plans/BROWSER.md §17): theirs first, a vocabulary's name or WordNet
word equal to what they typed, then names and words starting with it, the
vocabularies shown first; never more than asked."""

import unittest

from ontodag.suggest import Vocabularies, key, suggest

TEXTS = {
    "core": "information '*'\nimage information\nphotograph image physical-object\n"
            "physical-object '*'\nphotography service\nservice '*'\nphotographer artist\nartist '*'\n",
    "computing": "information '*'\nimage-file media-file\nmedia-file '*'\n",
    "space": "photograph '*'\nastrophotograph photograph\n",
}
WORDS = (("photograph", ("photo", "exposure", "picture", "pic")),
         ("image", ("picture",)),
         ("not-in-any-pack", ("ghost",)))


class TestSuggest(unittest.TestCase):
    def setUp(self):
        self.vocab = Vocabularies(TEXTS, words=WORDS)

    def names(self, text, **kw):
        return [s["name"] for s in suggest(text, self.vocab, **kw)]

    def test_what_is_typed_is_spelled_as_names_are(self):
        self.assertEqual(key("  Photo  Album "), "photo-album")

    def test_a_word_finds_the_category_it_names(self):
        first = suggest("photo", self.vocab)[0]
        self.assertEqual((first["name"], first["word"]), ("photograph", "photo"))
        self.assertEqual(first["places"], [["core", ["image", "physical-object"]]])
        self.assertEqual(first["also"], ["photo", "exposure", "picture", "pic"])

    def test_a_word_that_names_two_categories_offers_both(self):
        self.assertEqual(self.names("picture")[:2], ["image", "photograph"])

    def test_words_of_names_no_pack_has_are_dropped(self):
        self.assertEqual(self.names("ghost"), [])

    def test_your_own_names_come_first(self):
        self.assertEqual(self.names("phot", mine=["photos-of-rome", "Photo-Album"])[:2],
                         ["Photo-Album", "photos-of-rome"])

    def test_the_vocabularies_shown_come_first(self):
        self.assertEqual(self.names("image", shown=["computing"])[:2], ["image", "image-file"])
        self.assertEqual(self.names("ima", shown=["computing"])[0], "image-file")
        self.assertEqual(self.names("ima", shown=["core"])[0], "image")

    def test_a_pack_that_borrows_a_core_name_does_not_place_it(self):
        self.assertEqual(self.vocab.packs_having("photograph"), ["core"])
        self.assertEqual(self.vocab.packs_having("astrophotograph"), ["space"])

    def test_never_more_than_asked(self):
        self.assertEqual(len(self.names("p", limit=2)), 2)
        self.assertEqual(self.names(""), [])

    def test_a_name_is_offered_once(self):
        found = self.names("photograph", mine=["photograph"])
        self.assertEqual(found.count("photograph"), 1)
        self.assertTrue(suggest("photograph", self.vocab, mine=["photograph"])[0]["mine"])


class TestCoreWords(unittest.TestCase):
    def test_core_words_name_core_categories_only(self):
        from ontodag.core_ontology import CORE
        from ontodag.core_words import WORDS
        names = {n for n, _ in CORE}
        self.assertTrue(WORDS)
        self.assertEqual([n for n, _ in WORDS if n not in names], [])
        self.assertEqual([n for n, ws in WORDS if n in ws], [])
        self.assertIn("photo", dict(WORDS)["photograph"])


if __name__ == "__main__":
    unittest.main()
