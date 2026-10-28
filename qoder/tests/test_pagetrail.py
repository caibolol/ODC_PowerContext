import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pagetrail import corpus, review
from pagetrail.embedding import LocalHashEmbedding, embed
from pagetrail.library import Library, day_number


class EmbeddingTest(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(embed("多副本一致性"), embed("多副本一致性"))

    def test_normalized(self):
        vector = embed("Paxos 两阶段投票")
        norm = sum(value * value for value in vector) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=6)

    def test_callable_with_list(self):
        embeddings = LocalHashEmbedding()(["数据库", "机器学习"])
        self.assertEqual(len(embeddings), 2)
        self.assertEqual(len(embeddings[0]), 512)


class ReviewTest(unittest.TestCase):
    def test_first_good(self):
        state = review.new_state(100)
        updated = review.grade(state, "good", 100)
        self.assertEqual(updated["state"], "review")
        self.assertEqual(updated["interval_days"], 1)
        self.assertEqual(updated["due_day"], 101)
        self.assertEqual(updated["reps"], 1)

    def test_again_counts_lapse(self):
        state = review.grade(review.new_state(100), "good", 100)
        updated = review.grade(state, "again", 101)
        self.assertEqual(updated["state"], "learning")
        self.assertEqual(updated["lapses"], 1)
        self.assertLess(updated["ease"], state["ease"])

    def test_interval_grows(self):
        state = review.new_state(100)
        for day in (100, 101, 102):
            state = review.grade(state, "good", day)
        self.assertGreaterEqual(state["interval_days"], 3)

    def test_invalid_grade(self):
        with self.assertRaises(ValueError):
            review.grade(review.new_state(100), "perfect", 100)


class LibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = tempfile.mkdtemp(prefix="pagetrail-test-")
        cls.library = Library(cls.path).open()
        cls.library.ingest(corpus.passages())

    @classmethod
    def tearDownClass(cls):
        cls.library.close()
        shutil.rmtree(cls.path, ignore_errors=True)

    def test_ingest_count(self):
        self.assertEqual(self.library.describe()["count"], 16)

    def test_hybrid_top1(self):
        rows = self.library.search("Paxos 两阶段投票", limit=3)
        self.assertEqual(rows[0]["id"], "p-db-1")

    def test_fulltext_chinese(self):
        rows = self.library.fulltext("多副本", limit=5)
        self.assertIn("p-db-2", [row["id"] for row in rows])

    def test_vector_returns_limit(self):
        rows = self.library.vector("过拟合", limit=3)
        self.assertEqual(len(rows), 3)

    def test_citation_metadata(self):
        row = self.library.search("验证集过拟合", limit=1)[0]
        self.assertTrue(row["meta"]["title"])
        self.assertTrue(row["meta"]["source"])
        self.assertGreaterEqual(row["meta"]["page"], 1)

    def test_filter_by_doc(self):
        rows = self.library.search("一致性", doc_id="doc-ml")
        self.assertTrue(rows)
        self.assertTrue(all(row["meta"]["doc_id"] == "doc-ml" for row in rows))

    def test_filter_by_doc_and_topic(self):
        rows = self.library.search("Paxos", doc_id="doc-db", topic="共识算法")
        self.assertTrue(rows)
        self.assertTrue(all(row["meta"]["doc_id"] == "doc-db" for row in rows))
        self.assertTrue(all(row["meta"]["topic"] == "共识算法" for row in rows))

    def test_channels_disagree(self):
        channels = self.library.compare("学习率震荡", limit=3)
        self.assertNotEqual(channels["fulltext"][0]["id"], channels["vector"][0]["id"])
        self.assertEqual(channels["hybrid"][0]["id"], "p-ml-1")

    def test_hybrid_records_request(self):
        self.library.search("Paxos", limit=2)
        request = self.library.last_request
        self.assertEqual(request["rank"], {"rrf": {}})
        self.assertIn("$contains", request["query"]["where_document"])

    def test_rate_updates_state(self):
        today = day_number()
        updated = self.library.rate("p-db-5", "good", today)
        self.assertEqual(updated["state"], "review")
        self.assertEqual(updated["due_day"], today + 1)
        stored = self.library.get("p-db-5")["meta"]
        self.assertEqual(stored["state"], "review")
        self.assertEqual(stored["reps"], 1)

    def test_due_queue(self):
        today = day_number()
        self.library.rate("p-ml-2", "again", today)
        due_tomorrow = [row["id"] for row in self.library.due(today + 1)]
        self.assertIn("p-ml-2", due_tomorrow)
        self.assertNotIn("p-ml-2", [row["id"] for row in self.library.due(today)])

    def test_stats_consistent(self):
        stats = self.library.stats()
        self.assertEqual(stats["total"], 16)
        self.assertEqual(sum(stats["by_doc"].values()), 16)


WRITE_SCRIPT = """
import sys
sys.path.insert(0, sys.argv[2])
from pagetrail import corpus
from pagetrail.library import Library, day_number

with Library(sys.argv[1]) as library:
    library.ingest(corpus.passages())
    library.rate("p-rag-3", "hard", day_number())
"""


class PersistenceTest(unittest.TestCase):
    def test_state_survives_another_process(self):
        path = tempfile.mkdtemp(prefix="pagetrail-persist-")
        root = str(Path(__file__).resolve().parents[1])
        env = dict(os.environ, PYTHONPATH=root)
        try:
            writer = subprocess.run(
                [sys.executable, "-c", WRITE_SCRIPT, path, root],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
            )
            self.assertEqual(writer.returncode, 0, writer.stderr)
            reader = subprocess.run(
                [sys.executable, "-m", "pagetrail.state_probe", "--path", path, "--id", "p-rag-3"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
            )
            self.assertEqual(reader.returncode, 0, reader.stderr)
            meta = json.loads(reader.stdout)["meta"]
            self.assertEqual(meta["state"], "review")
            self.assertEqual(meta["reps"], 1)
            self.assertEqual(meta["due_day"], day_number() + 1)
        finally:
            shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
