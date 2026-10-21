import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from repo_eval_workbench.cli import main


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def invoke(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main(arguments)
        return result, out.getvalue(), err.getvalue()

    def test_audit_demo_json(self):
        code, text, _ = self.invoke(["audit", str(ROOT / "examples/demo-repo")])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(text)["findings"]), 4)

    def test_audit_policy(self):
        code, _, _ = self.invoke(
            ["audit", str(ROOT / "examples/demo-repo"), "--fail-on", "warning"]
        )
        self.assertEqual(code, 1)

    def test_missing_audit_root_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            code, text, _ = self.invoke(["audit", str(Path(directory) / "absent")])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(text)["files_scanned"], 0)

    def test_evaluate_example(self):
        code, text, _ = self.invoke(
            [
                "evaluate",
                "--dataset",
                str(ROOT / "data/benchmark.jsonl"),
                "--predictions",
                str(ROOT / "data/example_predictions.jsonl"),
            ]
        )
        self.assertEqual(code, 0)
        self.assertTrue(0 <= json.loads(text)["score"] <= 1)

    def test_threshold_failure(self):
        code, _, _ = self.invoke(
            [
                "evaluate",
                "--dataset",
                str(ROOT / "data/benchmark.jsonl"),
                "--predictions",
                str(ROOT / "data/example_predictions.jsonl"),
                "--fail-under",
                "1",
            ]
        )
        self.assertEqual(code, 1)

    def test_baseline_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            output = str(Path(directory) / "baseline.jsonl")
            code, _, _ = self.invoke(
                ["baseline", "--dataset", str(ROOT / "data/benchmark.jsonl"), "--output", output]
            )
            self.assertEqual(code, 0)
            code, text, _ = self.invoke(
                [
                    "evaluate",
                    "--dataset",
                    str(ROOT / "data/benchmark.jsonl"),
                    "--predictions",
                    output,
                ]
            )
            self.assertEqual(code, 0)
            self.assertGreaterEqual(json.loads(text)["score"], 0.90)

    def test_baseline_rejects_syntax_error_without_clean_prediction(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "dataset.jsonl"
            output = Path(directory) / "predictions.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "id": "invalid",
                        "path": "a.py",
                        "source": "def broken(:\n",
                        "expected": [],
                        "explanation": "Malformed Python",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            code, text, err = self.invoke(
                ["baseline", "--dataset", str(dataset), "--output", str(output)]
            )
            self.assertEqual(code, 2)
            self.assertEqual(text, "")
            self.assertIn("could not analyze", err)
            self.assertFalse(output.exists())

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.txt"
            output.write_text("keep me", encoding="utf-8")
            code, _, err = self.invoke(
                ["audit", str(ROOT / "examples/demo-repo"), "--output", str(output)]
            )
            self.assertEqual(code, 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep me")
            self.assertIn("repo-eval:", err)

    def test_baseline_respects_prediction_finding_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "dataset.jsonl"
            output = Path(directory) / "predictions.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "id": "many",
                        "path": "a.py",
                        "source": "eval('1')\n" * 129,
                        "expected": [],
                        "explanation": "Exceeds prediction finding bound",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            code, _, err = self.invoke(
                ["baseline", "--dataset", str(dataset), "--output", str(output)]
            )
            self.assertEqual(code, 2)
            self.assertIn("128 findings", err)
            self.assertFalse(output.exists())

    def test_missing_predictions_file(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _, err = self.invoke(
                [
                    "evaluate",
                    "--dataset",
                    str(ROOT / "data/benchmark.jsonl"),
                    "--predictions",
                    str(Path(directory) / "absent"),
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("repo-eval:", err)

    def test_nonfinite_threshold_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["evaluate", "--dataset", "a", "--predictions", "b", "--fail-under", "nan"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
