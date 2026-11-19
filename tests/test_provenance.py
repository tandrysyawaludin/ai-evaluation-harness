"""Results provenance: gold-set hash and harness git commit."""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evalharness import run_eval
from evalharness.run_eval import ROOT, build_provenance, render_report, run


def _git(*args, cwd):
    return subprocess.run(["git", "-C", cwd] + list(args),
                          capture_output=True, text=True, check=True)


class TestBuildProvenance(unittest.TestCase):
    def test_gold_hash_is_sha256_of_file_bytes(self):
        gold_path = os.path.join(ROOT, "data", "gold.jsonl")
        with open(gold_path, "rb") as f:
            expected = hashlib.sha256(f.read()).hexdigest()
        prov = build_provenance(gold_path)
        self.assertEqual(prov["gold_path"], "data/gold.jsonl")
        self.assertEqual(prov["gold_sha256"], expected)
        self.assertEqual(len(prov["gold_sha256"]), 64)

    def test_harness_commit_matches_head(self):
        prov = build_provenance(os.path.join(ROOT, "data", "gold.jsonl"))
        head = _git("rev-parse", "HEAD", cwd=ROOT).stdout.strip()
        self.assertEqual(prov["harness_commit"], head)
        self.assertEqual(len(head), 40)

    def test_dirty_flag_tracks_uncommitted_changes(self):
        # A throwaway repo, so the test does not depend on the state
        # of the real checkout at test time.
        with tempfile.TemporaryDirectory() as tmp:
            _git("init", "-q", cwd=tmp)
            gold_path = os.path.join(tmp, "gold.jsonl")
            with open(gold_path, "w") as f:
                f.write('{"id": "q001"}\n')
            _git("add", "gold.jsonl", cwd=tmp)
            _git("-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-qm", "gold", cwd=tmp)
            head = _git("rev-parse", "HEAD", cwd=tmp).stdout.strip()
            prov = build_provenance(gold_path, repo_root=tmp)
            self.assertEqual(prov["harness_commit"], head)
            self.assertFalse(prov["harness_dirty"])
            with open(gold_path, "a") as f:
                f.write('{"id": "q002"}\n')
            prov = build_provenance(gold_path, repo_root=tmp)
            self.assertTrue(prov["harness_dirty"])
            # The hash follows the file, not the commit: editing the
            # gold set changes the hash even before any new commit.
            with open(gold_path, "rb") as f:
                self.assertEqual(prov["gold_sha256"],
                                 hashlib.sha256(f.read()).hexdigest())
            self.assertNotEqual(
                prov["gold_sha256"],
                hashlib.sha256(b'{"id": "q001"}\n').hexdigest())

    def test_non_git_directory_degrades_to_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            gold_path = os.path.join(tmp, "gold.jsonl")
            with open(gold_path, "w") as f:
                f.write('{"id": "q001"}\n')
            prov = build_provenance(gold_path, repo_root=tmp)
            self.assertIsNone(prov["harness_commit"])
            self.assertIsNone(prov["harness_dirty"])
            # The gold hash still works: it needs only the file.
            self.assertEqual(len(prov["gold_sha256"]), 64)


class TestRunProvenance(unittest.TestCase):
    def test_run_carries_provenance(self):
        res = run(runs=1, seed=42)
        prov = res["provenance"]
        gold_path = os.path.join(ROOT, "data", "gold.jsonl")
        with open(gold_path, "rb") as f:
            self.assertEqual(prov["gold_sha256"],
                             hashlib.sha256(f.read()).hexdigest())
        head = _git("rev-parse", "HEAD", cwd=ROOT).stdout.strip()
        self.assertEqual(prov["harness_commit"], head)
        self.assertIn(prov["harness_dirty"], (True, False))

    def test_report_renders_provenance_in_header(self):
        res = run(runs=1, seed=42)
        report = render_report(res)
        prov = res["provenance"]
        self.assertIn("Provenance: gold set `data/gold.jsonl` SHA-256 "
                      f"`{prov['gold_sha256']}`", report)
        self.assertIn(f"harness commit `{prov['harness_commit']}`", report)
        # Header: the provenance line comes before the headline table.
        self.assertLess(report.index("Provenance:"),
                        report.index("## Headline results"))

    def test_report_without_provenance_omits_line(self):
        # Results files written before this feature have no key.
        res = run(runs=1, seed=42)
        del res["provenance"]
        self.assertNotIn("Provenance:", render_report(res))

    def test_report_renders_unknown_commit(self):
        res = run(runs=1, seed=42)
        res["provenance"]["harness_commit"] = None
        res["provenance"]["harness_dirty"] = None
        report = render_report(res)
        self.assertIn("harness commit unknown (not a git checkout)", report)
        self.assertIn("working-tree state unknown", report)

    def test_report_flags_dirty_tree(self):
        res = run(runs=1, seed=42)
        res["provenance"]["harness_dirty"] = True
        self.assertIn("⚠ working tree had uncommitted changes",
                      render_report(res))

    def test_cli_writes_provenance_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["run_eval", "--runs", "1", "--seed", "42",
                    "--out-dir", tmp]
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    run_eval.main()
            with open(os.path.join(tmp, "results.json")) as f:
                res = json.load(f)
            prov = res["provenance"]
            self.assertEqual(len(prov["gold_sha256"]), 64)
            self.assertEqual(len(prov["harness_commit"]), 40)
            with open(os.path.join(tmp, "report.md")) as f:
                self.assertIn("Provenance:", f.read())


if __name__ == "__main__":
    unittest.main()
