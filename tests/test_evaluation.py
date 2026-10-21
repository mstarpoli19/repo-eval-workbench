"""Deterministic, offline evaluator tests; no sample source is executed."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from repo_eval_workbench.evaluation import (
    EvaluationError,
    MAX_EXPLANATION_CHARS,
    MAX_FINDINGS_PER_TASK,
    MAX_ID_CHARS,
    MAX_INPUT_BYTES,
    MAX_LINE_NUMBER,
    MAX_PATH_CHARS,
    MAX_RECORDS,
    MAX_SOURCE_BYTES,
    MAX_TOTAL_SOURCE_BYTES,
    RULE_IDS,
    evaluate,
    load_dataset,
    load_predictions,
)


ROOT = Path(__file__).resolve().parents[1]


def finding(rule: str = "mutable-default", line: int = 1) -> dict:
    return {"rule_id": rule, "line": line}


def task(identifier: str = "task", expected: list | None = None) -> dict:
    return {
        "id": identifier,
        "source": "def collect(value, items=[]):\n    items.append(value)\n    return items\n",
        "path": "synthetic/collect.py",
        "expected": [finding()] if expected is None else expected,
        "explanation": "An authored synthetic shared-list default.",
    }


class ScoringTests(unittest.TestCase):
    def test_perfect_predictions_score_one_and_preserve_input(self):
        dataset = [task(), task("clean", [])]
        predictions = [{"id": row["id"], "findings": row["expected"]} for row in dataset]
        original_dataset, original_predictions = copy.deepcopy(dataset), copy.deepcopy(predictions)
        result = evaluate(dataset, predictions)
        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["dataset_count"], 2)
        self.assertEqual(result["prediction_count"], 2)
        self.assertEqual(
            result["metrics"],
            {"micro_precision": 1, "micro_recall": 1, "micro_f1": 1, "task_coverage": 1},
        )
        self.assertEqual(result["tasks"][0]["true_positives"], [finding()])
        self.assertEqual(result["tasks"][0]["false_positives"], [])
        self.assertEqual(result["tasks"][0]["false_negatives"], [])
        self.assertEqual(dataset, original_dataset)
        self.assertEqual(predictions, original_predictions)

    def test_missing_is_zero_even_for_clean_task(self):
        result = evaluate([task(), task("clean", [])], [])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["metrics"]["task_coverage"], 0)
        self.assertEqual(result["metrics"]["micro_f1"], 0)
        self.assertEqual([row["status"] for row in result["tasks"]], ["missing", "missing"])
        self.assertEqual(result["tasks"][0]["false_negatives"], [finding()])
        self.assertEqual(result["tasks"][1]["score"], 0)

    def test_explicit_clean_prediction_scores_one(self):
        result = evaluate([task("clean", [])], [{"id": "clean", "findings": []}])
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["tasks"][0]["status"], "evaluated")
        self.assertEqual(result["metrics"]["micro_precision"], 1)
        self.assertEqual(result["metrics"]["micro_recall"], 1)
        self.assertEqual(result["metrics"]["micro_f1"], 1)

    def test_missing_clean_micro_convention_is_distinct_from_task_score(self):
        result = evaluate([task("clean", [])], [])
        self.assertEqual(result["score"], 0)
        self.assertEqual(
            result["metrics"],
            {"micro_precision": 1, "micro_recall": 1, "micro_f1": 1, "task_coverage": 0},
        )

    def test_zero_denominator_with_only_false_positive(self):
        result = evaluate([task("clean", [])], [{"id": "clean", "findings": [finding()]}])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["metrics"]["micro_precision"], 0)
        self.assertEqual(result["metrics"]["micro_recall"], 0)
        self.assertEqual(result["metrics"]["micro_f1"], 0)

    def test_zero_denominator_with_only_false_negative(self):
        result = evaluate([task()], [{"id": "task", "findings": []}])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["metrics"]["micro_precision"], 0)
        self.assertEqual(result["metrics"]["micro_recall"], 0)
        self.assertEqual(result["metrics"]["micro_f1"], 0)

    def test_partial_credit_uses_exact_rule_and_line(self):
        dataset = [task(expected=[finding(), finding("bare-except", 2)])]
        predictions = [{"id": "task", "findings": [finding(), finding("bare-except", 3)]}]
        result = evaluate(dataset, predictions)
        row = result["tasks"][0]
        self.assertEqual(row["score"], 0.5)
        self.assertEqual(row["true_positives"], [finding()])
        self.assertEqual(row["false_positives"], [finding("bare-except", 3)])
        self.assertEqual(row["false_negatives"], [finding("bare-except", 2)])
        self.assertEqual(result["metrics"]["micro_f1"], 0.5)

    def test_macro_task_average_not_micro_f1(self):
        dataset = [
            task(expected=[finding(), finding("bare-except", 2)]),
            task("clean", []),
            task("missing"),
        ]
        predictions = [{"id": "task", "findings": [finding()]}, {"id": "clean", "findings": []}]
        result = evaluate(dataset, predictions)
        self.assertAlmostEqual(result["score"], (2 / 3 + 1 + 0) / 3)
        self.assertAlmostEqual(result["metrics"]["micro_precision"], 1)
        self.assertAlmostEqual(result["metrics"]["micro_recall"], 1 / 3)
        self.assertAlmostEqual(result["metrics"]["micro_f1"], 0.5)
        self.assertAlmostEqual(result["metrics"]["task_coverage"], 2 / 3)

    def test_same_line_different_rules_remain_distinct(self):
        expected = [finding("dynamic-exec"), finding()]
        result = evaluate([task(expected=expected)], [{"id": "task", "findings": [finding()]}])
        self.assertAlmostEqual(result["score"], 2 / 3)
        self.assertEqual(result["tasks"][0]["false_negatives"], [finding("dynamic-exec")])

    def test_finding_order_is_irrelevant_and_output_is_deterministic(self):
        expected = [finding("shell-true", 3), finding("dynamic-exec", 1), finding()]
        first = evaluate([task(expected=expected)], [{"id": "task", "findings": expected[::-1]}])
        second = evaluate([task(expected=expected[::-1])], [{"id": "task", "findings": expected}])
        self.assertEqual(first, second)
        self.assertEqual(
            first["tasks"][0]["true_positives"],
            [finding("dynamic-exec"), finding(), finding("shell-true", 3)],
        )

    def test_sources_and_model_payloads_are_never_executed(self):
        row = task(expected=[])
        row["source"] = "raise RuntimeError('source must remain inert')\n"
        with (
            patch("builtins.exec", side_effect=AssertionError("must not execute")),
            patch("builtins.eval", side_effect=AssertionError("must not evaluate")),
        ):
            self.assertEqual(evaluate([row], [{"id": "task", "findings": []}])["score"], 1)


class ValidationTests(unittest.TestCase):
    def test_empty_dataset_rejected_and_empty_predictions_allowed(self):
        with self.assertRaises(EvaluationError):
            evaluate([], [])
        self.assertEqual(evaluate([task()], [])["score"], 0)

    def test_dataset_and_prediction_containers_must_be_lists(self):
        for dataset, predictions in (({}, []), ((task(),), []), ([task()], {}), ([task()], ())):
            with (
                self.subTest(
                    dataset=type(dataset).__name__, predictions=type(predictions).__name__
                ),
                self.assertRaises(EvaluationError),
            ):
                evaluate(dataset, predictions)

    def test_exact_record_fields_are_required(self):
        for field in task():
            row = task()
            del row[field]
            with self.subTest(missing=field), self.assertRaises(EvaluationError):
                evaluate([row], [])
        row = task()
        row["extra"] = "not accepted"
        with self.assertRaises(EvaluationError):
            evaluate([row], [])
        for prediction in (
            {"id": "task"},
            {"findings": []},
            {"id": "task", "findings": [], "score": 1},
            ["task", []],
        ):
            with self.subTest(prediction=prediction), self.assertRaises(EvaluationError):
                evaluate([task()], [prediction])

    def test_duplicate_dataset_and_prediction_ids_rejected(self):
        with self.assertRaisesRegex(EvaluationError, "duplicate dataset id"):
            evaluate([task(), task()], [])
        with self.assertRaisesRegex(EvaluationError, "duplicate prediction id"):
            evaluate([task()], [{"id": "task", "findings": []}] * 2)

    def test_unknown_prediction_id_rejected(self):
        with self.assertRaisesRegex(EvaluationError, "unknown prediction ids"):
            evaluate([task()], [{"id": "invented", "findings": []}])

    def test_dataset_string_fields_have_strict_types_and_bounds(self):
        for field in ("id", "path", "source", "explanation"):
            for value in (None, 1, True, [], {}, float("inf"), "\ud800"):
                row = task()
                row[field] = value
                with (
                    self.subTest(field=field, value=repr(value)),
                    self.assertRaises(EvaluationError),
                ):
                    evaluate([row], [])
        for field, limit in (
            ("id", MAX_ID_CHARS),
            ("path", MAX_PATH_CHARS),
            ("explanation", MAX_EXPLANATION_CHARS),
            ("source", MAX_SOURCE_BYTES),
        ):
            row = task()
            row[field] = "x" * (limit + 1)
            with self.subTest(field=field), self.assertRaises(EvaluationError):
                evaluate([row], [])
        for field in ("id", "path", "explanation"):
            row = task()
            row[field] = "  "
            with self.subTest(empty=field), self.assertRaises(EvaluationError):
                evaluate([row], [])

    def test_empty_source_allows_no_findings(self):
        row = task(expected=[])
        row["source"] = ""
        self.assertEqual(evaluate([row], [{"id": "task", "findings": []}])["score"], 1)
        row["expected"] = [finding()]
        with self.assertRaises(EvaluationError):
            evaluate([row], [])

    def test_unicode_separators_do_not_create_source_lines(self):
        for separator in ("\u2028", "\u2029", "\u0085"):
            row = task(expected=[finding("dynamic-exec", 2)])
            row["source"] = 'value = "' + separator + '"\neval("1")\n'
            predictions = [{"id": "task", "findings": [finding("dynamic-exec", 2)]}]
            with self.subTest(separator=repr(separator)):
                self.assertEqual(evaluate([row], predictions)["score"], 1)
                predictions[0]["findings"] = [finding("dynamic-exec", 3)]
                with self.assertRaisesRegex(EvaluationError, "source line count 2"):
                    evaluate([row], predictions)
                row["expected"] = [finding("dynamic-exec", 3)]
                with self.assertRaisesRegex(EvaluationError, "source line count 2"):
                    evaluate([row], [])

    def test_source_physical_lines_support_crlf_cr_and_no_final_newline(self):
        for newline in ("\n", "\r\n", "\r"):
            for trailing_newline in (False, True):
                row = task(expected=[finding("dynamic-exec", 2)])
                row["source"] = newline.join(('value = "text"', 'eval("1")'))
                if trailing_newline:
                    row["source"] += newline
                with self.subTest(newline=repr(newline), trailing=trailing_newline):
                    self.assertEqual(
                        evaluate([row], [{"id": "task", "findings": row["expected"]}])["score"], 1
                    )
                    with self.assertRaisesRegex(EvaluationError, "source line count 2"):
                        evaluate([row], [{"id": "task", "findings": [finding("dynamic-exec", 3)]}])
                    row["expected"] = [finding("dynamic-exec", 3)]
                    with self.assertRaisesRegex(EvaluationError, "source line count 2"):
                        evaluate([row], [])

    def test_findings_must_be_exact_objects_in_lists(self):
        invalid = [
            None,
            {},
            (),
            [None],
            [[]],
            [{}],
            [{"rule_id": "bare-except"}],
            [{"line": 1}],
            [{"rule_id": "bare-except", "line": 1, "message": "extra"}],
        ]
        for findings in invalid:
            with self.subTest(findings=findings):
                row = task()
                row["expected"] = findings
                with self.assertRaises(EvaluationError):
                    evaluate([row], [])
                with self.assertRaises(EvaluationError):
                    evaluate([task()], [{"id": "task", "findings": findings}])

    def test_line_types_and_range_rejected_in_both_schemas(self):
        for line in (True, False, 0, -1, 1.0, "1", None, [], float("nan"), MAX_LINE_NUMBER + 1, 4):
            with self.subTest(line=line):
                row = task(expected=[finding(line=line)])
                with self.assertRaises(EvaluationError):
                    evaluate([row], [])
                with self.assertRaises(EvaluationError):
                    evaluate([task()], [{"id": "task", "findings": [finding(line=line)]}])

    def test_unsupported_rules_rejected_in_both_schemas(self):
        for rule in ("unknown-rule", "", True, 1, None, []):
            with self.subTest(rule=rule):
                with self.assertRaises(EvaluationError):
                    evaluate([task(expected=[finding(rule)])], [])
                with self.assertRaises(EvaluationError):
                    evaluate([task()], [{"id": "task", "findings": [finding(rule)]}])

    def test_duplicate_findings_rejected_in_both_schemas(self):
        with self.assertRaisesRegex(EvaluationError, "duplicate finding"):
            evaluate([task(expected=[finding(), finding()])], [])
        with self.assertRaisesRegex(EvaluationError, "duplicate finding"):
            evaluate([task()], [{"id": "task", "findings": [finding(), finding()]}])

    def test_record_and_findings_limits(self):
        with self.assertRaises(EvaluationError):
            evaluate([task()] * (MAX_RECORDS + 1), [])
        with self.assertRaises(EvaluationError):
            evaluate([task()], [{"id": "task", "findings": []}] * (MAX_RECORDS + 1))
        excessive = [finding("bare-except", line) for line in range(1, MAX_FINDINGS_PER_TASK + 2)]
        with self.assertRaises(EvaluationError):
            evaluate([task()], [{"id": "task", "findings": excessive}])
        with self.assertRaises(EvaluationError):
            evaluate([task(expected=excessive)], [])

    def test_source_byte_limits_include_multibyte_text(self):
        row = task(expected=[])
        row["source"] = "\u2603" * (MAX_SOURCE_BYTES // 3 + 1)
        with self.assertRaisesRegex(EvaluationError, "bytes"):
            evaluate([row], [])
        count = MAX_TOTAL_SOURCE_BYTES // MAX_SOURCE_BYTES + 1
        rows = [task(str(index), []) for index in range(count)]
        for row in rows:
            row["source"] = "x" * MAX_SOURCE_BYTES
        with self.assertRaisesRegex(EvaluationError, "dataset sources"):
            evaluate(rows, [])

    def test_aggregate_serialized_size_bound_for_direct_callers(self):
        rows = [task(str(index), []) for index in range(200)]
        for row in rows:
            row["explanation"] = "\u2603" * MAX_EXPLANATION_CHARS
        with self.assertRaisesRegex(EvaluationError, "serialized bytes"):
            evaluate(rows, [])


class LoaderTests(unittest.TestCase):
    def load_text(self, text: str, *, dataset: bool = True):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            path.write_text(text, encoding="utf-8")
            return load_dataset(path) if dataset else load_predictions(path)

    def test_loaders_round_trip_and_allow_blank_separator_lines(self):
        self.assertEqual(self.load_text("\n" + json.dumps(task()) + "\n\n"), [task()])
        predictions = {"id": "task", "findings": [finding()]}
        self.assertEqual(self.load_text(json.dumps(predictions), dataset=False), [predictions])
        self.assertEqual(self.load_text("\n", dataset=False), [])
        with self.assertRaises(EvaluationError):
            self.load_text("\n")

    def test_unicode_separators_inside_json_strings_round_trip(self):
        for separator in ("\u2028", "\u2029", "\u0085"):
            row = task("task" + separator, [finding("dynamic-exec", 2)])
            row["source"] = 'value = "' + separator + '"\neval("1")\n'
            row["explanation"] = "A separator " + separator + " remains string data."
            prediction = {"id": row["id"], "findings": row["expected"]}
            with self.subTest(separator=repr(separator)):
                loaded = self.load_text(json.dumps(row, ensure_ascii=False) + "\r\n")
                predictions = self.load_text(
                    json.dumps(prediction, ensure_ascii=False) + "\r\n", dataset=False
                )
                self.assertEqual(loaded, [row])
                self.assertEqual(predictions, [prediction])
                self.assertEqual(evaluate(loaded, predictions)["score"], 1)

    def test_unicode_separator_outside_json_is_not_a_blank_record(self):
        for separator in ("\u2028", "\u2029", "\u0085"):
            with self.subTest(separator=repr(separator)), self.assertRaises(EvaluationError):
                self.load_text(separator, dataset=False)

    def test_malformed_nonobject_and_duplicate_json_keys_rejected(self):
        malformed = [
            '{"id":',
            "null",
            "[]",
            "true",
            "1",
            '{"id":"first","id":"second"}',
            '{"id":"task","findings":[{"rule_id":"bare-except","line":1,"line":2}]}',
        ]
        for value in malformed:
            for dataset in (True, False):
                with self.subTest(value=value, dataset=dataset), self.assertRaises(EvaluationError):
                    self.load_text(value, dataset=dataset)

    def test_nonfinite_json_values_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e999"):
            payload = '{"id":"task","findings":[{"rule_id":"bare-except","line":' + value + "}]}"
            with self.subTest(value=value), self.assertRaises(EvaluationError):
                self.load_text(payload, dataset=False)

    def test_duplicate_ids_in_jsonl_rejected(self):
        with self.assertRaises(EvaluationError):
            self.load_text(json.dumps(task()) + "\n" + json.dumps(task()))
        value = json.dumps({"id": "task", "findings": []})
        with self.assertRaises(EvaluationError):
            self.load_text(value + "\n" + value, dataset=False)

    def test_prediction_source_bounds_checked_when_dataset_is_available(self):
        predictions = self.load_text(
            '{"id":"task","findings":[{"rule_id":"bare-except","line":99}]}', dataset=False
        )
        with self.assertRaisesRegex(EvaluationError, "source line count"):
            evaluate([task()], predictions)

    def test_invalid_utf8_and_oversized_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            path.write_bytes(b"\xff")
            with self.assertRaisesRegex(EvaluationError, "UTF-8"):
                load_dataset(path)
            path.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
            for loader in (load_dataset, load_predictions):
                with (
                    self.subTest(loader=loader.__name__),
                    self.assertRaisesRegex(EvaluationError, "bytes"),
                ):
                    loader(path)

    def test_jsonl_record_limit(self):
        rows = [json.dumps({"id": str(index), "findings": []}) for index in range(MAX_RECORDS + 1)]
        with self.assertRaisesRegex(EvaluationError, "records"):
            self.load_text("\n".join(rows), dataset=False)

    def test_deeply_nested_json_rejected_cleanly(self):
        with self.assertRaises(EvaluationError):
            self.load_text("[" * 2000 + "0" + "]" * 2000)

    def test_missing_path_error_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(EvaluationError, "cannot read input"):
                load_dataset(Path(directory) / "missing.jsonl")


class AuthoredBenchmarkTests(unittest.TestCase):
    def test_benchmark_has_balanced_synthetic_cases_and_valid_python(self):
        dataset = load_dataset(ROOT / "data" / "benchmark.jsonl")
        self.assertGreaterEqual(len(dataset), 20)
        clean = sum(not row["expected"] for row in dataset)
        self.assertGreaterEqual(clean, len(dataset) // 3)
        self.assertGreaterEqual(len(dataset) - clean, len(dataset) // 3)
        rules = {item["rule_id"] for row in dataset for item in row["expected"]}
        self.assertEqual(rules, RULE_IDS)
        for row in dataset:
            with self.subTest(identifier=row["id"]):
                self.assertTrue(row["path"].startswith("synthetic/"))
                ast.parse(row["source"], filename=row["path"])
        self.assertTrue(
            any(
                len({item["rule_id"] for item in row["expected"]})
                > len({item["line"] for item in row["expected"]})
                for row in dataset
            )
        )

    def test_perfect_authored_predictions_score_one(self):
        dataset = load_dataset(ROOT / "data" / "benchmark.jsonl")
        predictions = [{"id": row["id"], "findings": row["expected"]} for row in dataset]
        result = evaluate(dataset, predictions)
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["metrics"]["micro_f1"], 1)

    def test_example_predictions_are_valid_imperfect_and_reproducible(self):
        dataset = load_dataset(ROOT / "data" / "benchmark.jsonl")
        predictions = load_predictions(ROOT / "data" / "example_predictions.jsonl")
        result = evaluate(dataset, predictions)
        self.assertEqual(result, evaluate(dataset, predictions))
        self.assertGreater(result["score"], 0)
        self.assertLess(result["score"], 1)
        self.assertEqual(result["dataset_count"], 24)
        self.assertEqual(result["prediction_count"], 23)
        self.assertAlmostEqual(result["score"], 23 / 36)
        self.assertAlmostEqual(result["metrics"]["micro_precision"], 11 / 15)
        self.assertAlmostEqual(result["metrics"]["micro_recall"], 11 / 18)
        self.assertAlmostEqual(result["metrics"]["micro_f1"], 2 / 3)
        self.assertAlmostEqual(result["metrics"]["task_coverage"], 23 / 24)


if __name__ == "__main__":
    unittest.main()
