"""Guidelines doc: it must exist, cover the three topics the roadmap item
promises (adding questions, labelling answers, reviewing judge
disagreements), and point at the real datasets and commands it describes,
so the doc cannot silently drift from the harness it documents."""

import os
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
GUIDELINES = os.path.join(ROOT, "docs", "GUIDELINES.md")


class TestGuidelines(unittest.TestCase):
    def setUp(self):
        with open(GUIDELINES) as f:
            self.text = f.read()

    def test_doc_exists_and_covers_all_three_topics(self):
        for heading in ("Adding gold questions",
                        "Labelling answers",
                        "Reviewing judge disagreements"):
            self.assertIn(heading, self.text)

    def test_doc_points_at_real_datasets(self):
        for path in ("data/gold.jsonl", "data/human_labels.jsonl"):
            self.assertIn(path, self.text)
            self.assertTrue(os.path.exists(os.path.join(ROOT, path)),
                            f"{path} referenced by the guidelines is missing")

    def test_doc_names_real_commands_and_thresholds(self):
        self.assertIn("evalharness.validate", self.text)
        self.assertIn("run_eval", self.text)
        # The release-gate threshold from DESIGN.md section 4.
        self.assertIn("0.6", self.text)

    def test_design_links_to_guidelines(self):
        with open(os.path.join(ROOT, "docs", "DESIGN.md")) as f:
            self.assertIn("GUIDELINES.md", f.read())


if __name__ == "__main__":
    unittest.main()
