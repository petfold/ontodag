"""Your files organised where they are (ontodag.folders, BROWSER.md §17):
a folder read and never written, its layer (each content under its kind),
documents named by their files with their contents as versions below
them (question 40), an edit recognised by name, copies as one version,
single files, and the hash cache that spares reading what did not
change."""

import hashlib
import os
import tempfile
import time
import unittest

from ontodag import OntoDAG
from ontodag import folders as F


def write(root, path, text, mtime=None):
    full = os.path.join(root, *path.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(text)
    if mtime is not None:
        os.utime(full, (mtime, mtime))
    return full


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class TestLookingAtAFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        write(self.root, "Photos/Rome 2026/IMG_2041.jpg", "rome photo")
        write(self.root, "Downloads/IMG_2041 (1).jpg", "rome photo")
        write(self.root, "Notes/reading-list.md", "books")
        write(self.root, "Notes/.reading-list.md.swp", "editor")
        write(self.root, ".git/config", "git")
        write(self.root, "node_modules/x/index.js", "js")
        write(self.root, "firmware.bin", "bytes")

    def tearDown(self):
        self.tmp.cleanup()

    def test_kinds_come_from_extensions(self):
        self.assertEqual(F.kind_of("a/IMG.JPG"), "image-file")
        self.assertEqual(F.kind_of("notes.md"), "text-file")
        self.assertEqual(F.kind_of("tax.xlsx"), "document")
        self.assertIsNone(F.kind_of("README"))
        self.assertIsNone(F.kind_of(".bashrc"))
        self.assertIsNone(F.kind_of("firmware.bin"))

    def test_what_is_skipped(self):
        for path in (".git/config", "node_modules/x/a.js", "a/.hidden/b.txt", "notes.md~",
                     ".notes.md.swp", "Thumbs.db", ".DS_Store", "~$report.docx"):
            self.assertTrue(F.skipped(path), path)
        for path in ("Photos/IMG.jpg", "Notes/reading-list.md", "a.b/c.txt"):
            self.assertFalse(F.skipped(path), path)

    def test_a_scan_lists_and_hashes_what_is_not_skipped(self):
        seen = F.scan(self.root)
        self.assertEqual([s.path for s in seen],
                         ["Downloads/IMG_2041 (1).jpg", "Notes/reading-list.md",
                          "Photos/Rome 2026/IMG_2041.jpg", "firmware.bin"])
        self.assertEqual(seen[1].sha256, sha("books"))
        self.assertEqual(seen[1].size, 5)

    def test_copies_are_one_content_in_the_layer(self):
        folder = F.Folder(F.scan(self.root))
        self.assertEqual(len(folder.by_hash[sha("rome photo")]), 2)
        self.assertEqual(folder.layer(), sorted([
            (F.version_name(sha("rome photo")), ["image-file"]),
            (F.version_name(sha("books")), ["text-file"])]))

    def test_the_cache_spares_reading_what_did_not_change(self):
        cache = F.HashCache()
        first, again = {}, {}
        F.scan(self.root, cache=cache, stats=first)
        self.assertEqual((first["hashed"], first["cached"]), (4, 0))
        F.scan(self.root, cache=cache, stats=again)
        self.assertEqual((again["hashed"], again["cached"], again["bytes_read"]), (0, 4, 0))
        write(self.root, "Notes/reading-list.md", "more books", mtime=time.time() + 10)
        os.remove(os.path.join(self.root, "firmware.bin"))
        changed = {}
        seen = F.scan(self.root, cache=cache, stats=changed)
        self.assertEqual((changed["hashed"], changed["cached"]), (1, 2))
        self.assertIn(sha("more books"), {s.sha256 for s in seen})
        self.assertEqual(len(cache.entries), 3)

    def test_the_cache_is_saved_and_read_back(self):
        cache = F.HashCache()
        F.scan(self.root, cache=cache)
        path = os.path.join(self.root, "..", "cache-for-test.json")
        try:
            cache.save(path)
            self.assertEqual(F.HashCache.load(path).entries, cache.entries)
        finally:
            os.remove(path)
        self.assertEqual(F.HashCache.load(path).entries, {})

    def test_large_files_can_wait(self):
        stats = {}
        seen = F.scan(self.root, hash_over=5, stats=stats)       # the two photos are 10 bytes
        self.assertEqual(stats["unhashed"], 2)
        self.assertEqual([s.path for s in seen if s.sha256], ["Notes/reading-list.md", "firmware.bin"])
        self.assertEqual(len(F.Folder(seen).unhashed), 2)


class TestFilingIntoYourStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.when = 1_790_000_000
        write(self.root, "Photos/Rome 2026/IMG_2041.jpg", "rome photo", self.when)
        write(self.root, "Downloads/IMG_2041 (1).jpg", "rome photo", self.when + 60)
        write(self.root, "Notes/reading-list.md", "books", self.when)
        self.dag = OntoDAG()

    def tearDown(self):
        self.tmp.cleanup()

    def look(self):
        return F.Folder(F.scan(self.root))

    def seen(self, folder, path):
        return next(s for s in folder.seen if s.path == path)

    def test_a_filed_file_is_a_document_with_its_content_below(self):
        folder = self.look()
        answer = F.file(self.dag, self.seen(folder, "Notes/reading-list.md"), ["notes"])
        self.assertEqual((answer["document"], answer["made"], answer["created"]),
                         ("reading-list.md", True, ["notes"]))
        self.assertGreater(answer["prelude"], 0)
        version = F.version_name(sha("books"))
        self.assertEqual(sorted(p.name for p in self.dag.nodes[version].parents),
                         ["reading-list.md", F.time_value(self.when)])
        self.assertEqual(F.documents(self.dag), {"reading-list.md": [version]})
        self.assertEqual([i.name for i in self.dag.get(["notes"]) if F.is_version(i.name)], [version])

    def test_a_copy_files_into_the_same_document(self):
        folder = self.look()
        F.file(self.dag, self.seen(folder, "Photos/Rome 2026/IMG_2041.jpg"), ["holiday"])
        answer = F.file(self.dag, self.seen(folder, "Downloads/IMG_2041 (1).jpg"), ["family"])
        self.assertEqual((answer["document"], answer["made"]), ("IMG_2041.jpg", False))
        self.assertEqual(sorted(p.name for p in self.dag.nodes["IMG_2041.jpg"].parents), ["family", "holiday"])

    def test_what_is_not_filed_yet(self):
        folder = self.look()
        F.file(self.dag, self.seen(folder, "Notes/reading-list.md"), ["notes"])
        self.assertEqual(list(F.unfiled(self.dag, folder)), [sha("rome photo")])

    def test_another_file_of_the_same_name_is_told_apart_by_its_folder(self):
        write(self.root, "Photos/Paris/IMG_2041.jpg", "paris photo")
        folder = self.look()
        F.file(self.dag, self.seen(folder, "Photos/Rome 2026/IMG_2041.jpg"), ["holiday"])
        answer = F.file(self.dag, self.seen(folder, "Photos/Paris/IMG_2041.jpg"), ["holiday"])
        self.assertEqual(answer["document"], "IMG_2041.jpg (Paris)")

    def test_a_file_named_as_a_typed_value_is_not_read_as_one(self):
        from ontodag import prelude
        prelude.apply(self.dag)
        write(self.root, "time(2026)", "odd name")
        folder = self.look()
        answer = F.file(self.dag, self.seen(folder, "time(2026)"), ["odd"])
        self.assertEqual(answer["document"], "time(2026) (file)")

    def test_the_layer_and_your_store_answer_together(self):
        folder = self.look()
        F.file(self.dag, self.seen(folder, "Photos/Rome 2026/IMG_2041.jpg"), ["holiday"])
        F.file(self.dag, self.seen(folder, "Notes/reading-list.md"), ["holiday"])
        view = OntoDAG()
        for item, kinds in folder.layer():
            for k in kinds:
                if k not in view.nodes:
                    view.put(k, [])
            view.put(item, kinds)
        view.merge(self.dag)
        found = [F.document_of(view, i.name) for i in view.get(["holiday", "image-file"]) if F.is_version(i.name)]
        self.assertEqual(found, ["IMG_2041.jpg"])
        self.assertNotIn("image-file", self.dag.nodes)      # the layer is never stored

    def test_an_edit_is_recognised_by_name(self):
        folder = self.look()
        F.file(self.dag, self.seen(folder, "Notes/reading-list.md"), ["notes"])
        write(self.root, "Notes/reading-list.md", "more books", self.when + 3600)
        folder = self.look()
        edits, ambiguous = F.recognise_edits(self.dag, folder)
        self.assertEqual([(s.path, d) for s, d in edits], [("Notes/reading-list.md", "reading-list.md")])
        self.assertEqual(ambiguous, [])
        F.attach(self.dag, edits[0][0], edits[0][1])
        self.assertEqual(F.versions_of(self.dag, "reading-list.md"),
                         sorted([F.version_name(sha("books")), F.version_name(sha("more books"))]))
        new = F.version_name(sha("more books"))
        self.assertIn(new, [i.name for i in self.dag.get(["notes"])])
        self.assertEqual([i.name for i in self.dag.get([F.time_value(self.when + 3600)])], [new])
        self.assertEqual(list(F.unfiled(self.dag, folder)), [sha("rome photo")])

    def test_an_edit_and_a_rename_together_are_not_guessed(self):
        folder = self.look()
        F.file(self.dag, self.seen(folder, "Notes/reading-list.md"), ["notes"])
        os.remove(os.path.join(self.root, "Notes", "reading-list.md"))
        write(self.root, "Notes/reading-list-2026.md", "more books")
        edits, ambiguous = F.recognise_edits(self.dag, self.look())
        self.assertEqual((edits, ambiguous), ([], []))

    def test_a_known_version_still_in_the_folder_is_not_an_edit(self):
        folder = self.look()
        F.file(self.dag, self.seen(folder, "Notes/reading-list.md"), ["notes"])
        write(self.root, "Archive/reading-list.md", "other books")
        edits, ambiguous = F.recognise_edits(self.dag, self.look())
        self.assertEqual((edits, ambiguous), ([], []))

    def test_two_documents_of_one_name_go_by_folder(self):
        write(self.root, "Work/notes.txt", "work")
        write(self.root, "Home/notes.txt", "home")
        folder = self.look()
        F.file(self.dag, self.seen(folder, "Work/notes.txt"), ["work"])
        F.file(self.dag, self.seen(folder, "Home/notes.txt"), ["home"])
        self.assertEqual(sorted(F.documents(self.dag)), ["notes.txt", "notes.txt (Home)"])
        write(self.root, "Home/notes.txt", "home, edited", self.when + 7200)
        edits, ambiguous = F.recognise_edits(self.dag, self.look())
        self.assertEqual([(s.path, d) for s, d in edits], [("Home/notes.txt", "notes.txt (Home)")])
        self.assertEqual(ambiguous, [])


class TestSingleFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dag = OntoDAG()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_single_file_is_named_with_its_folder(self):
        path = write(self.tmp.name, "Downloads/receipt.pdf", "paid")
        seen = F.look_at(path)
        self.assertEqual((seen.path, seen.name, seen.sha256), ("Downloads/receipt.pdf", "receipt.pdf", sha("paid")))
        self.assertEqual(F.file(self.dag, seen, ["taxes"])["document"], "receipt.pdf")
        with self.assertRaises(ValueError):
            F.look_at(os.path.join(self.tmp.name, "Downloads"))

    def test_the_person_says_when_it_is_a_new_version(self):
        first = F.look_at(write(self.tmp.name, "Notes/plan.md", "v1"))
        F.file(self.dag, first, ["notes"])
        second = F.look_at(write(self.tmp.name, "Desktop/plan.md", "v2"))
        self.assertEqual(F.named_like(self.dag, second), ["plan.md"])
        answer = F.file(self.dag, second, version_of="plan.md")
        self.assertEqual((answer["document"], answer["made"]), ("plan.md", False))
        self.assertEqual(len(F.versions_of(self.dag, "plan.md")), 2)
        with self.assertRaises(ValueError):
            F.file(self.dag, F.look_at(write(self.tmp.name, "x/other.md", "v3")), version_of="notes")

    def test_without_being_told_it_is_a_document_of_its_own(self):
        F.file(self.dag, F.look_at(write(self.tmp.name, "Notes/plan.md", "v1")), ["notes"])
        answer = F.file(self.dag, F.look_at(write(self.tmp.name, "Desktop/plan.md", "v2")), ["notes"])
        self.assertEqual(answer["document"], "plan.md (Desktop)")

    def test_the_cache_knows_a_single_file_too(self):
        cache = F.HashCache()
        path = write(self.tmp.name, "a/b.txt", "text")
        F.look_at(path, cache=cache)
        self.assertEqual(list(cache.entries.values()), [sha("text")])


if __name__ == "__main__":
    unittest.main()
