"""Offline evaluation of authored code-review findings; never execute inputs.

Task score is F1 over exact ``(rule_id, line)`` pairs. An explicitly supplied
clean prediction scores 1 for a clean task; an omitted prediction always scores
0, including for clean tasks. The overall score is the arithmetic mean of task
scores, not micro F1.

Micro metrics pool true/false positives and false negatives over all tasks,
treating missing predictions as empty findings. Precision is TP / (TP + FP),
recall is TP / (TP + FN), and F1 is 2TP / (2TP + FP + FN). A zero denominator
scores 0 unless both pooled expected and predicted findings are empty, in which
case all three micro metrics are 1. This can coexist with a low task score when
clean tasks are omitted; task_coverage is the fraction explicitly predicted.

Inputs are bounded, exact-schema JSON-compatible records. Limits apply both to
file loaders and to direct evaluate() callers. Source is inert text only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RULE_IDS = frozenset({"mutable-default", "bare-except", "shell-true", "dynamic-exec"})
SCHEMA_VERSION = "1.0"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 1000
MAX_SOURCE_BYTES = 64 * 1024
MAX_TOTAL_SOURCE_BYTES = 1024 * 1024
MAX_FINDINGS_PER_TASK = 128
MAX_ID_CHARS = 128
MAX_PATH_CHARS = 512
MAX_EXPLANATION_CHARS = 4096
MAX_LINE_NUMBER = 1_000_000


class EvaluationError(ValueError):
    """An invalid or oversized dataset or prediction input."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvaluationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise EvaluationError(f"non-finite JSON value is not allowed: {value}")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read at most the byte limit, so oversized or growing files stay bounded."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
    except (OSError, TypeError) as exc:
        raise EvaluationError(f"cannot read input: {exc}") from exc
    if len(raw) > MAX_INPUT_BYTES:
        raise EvaluationError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluationError("input must be valid UTF-8") from exc
    records: list[dict[str, Any]] = []
    # JSONL records end at LF, not at Unicode separators inside JSON strings.
    for line_number, line in enumerate(content.split("\n"), 1):
        if not line.strip(" \t\r"):
            continue
        if len(records) >= MAX_RECORDS:
            raise EvaluationError(f"input exceeds {MAX_RECORDS} records")
        try:
            record = json.loads(
                line,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (ValueError, RecursionError) as exc:
            raise EvaluationError(f"invalid JSON on line {line_number}: {exc}") from exc
        records.append(record)
    return records


def _fields(value: Any, expected: set[str], context: str) -> None:
    if type(value) is not dict or set(value) != expected:
        names = ", ".join(sorted(expected))
        raise EvaluationError(f"{context} must have exactly these fields: {names}")


def _text(value: Any, name: str, maximum: int, *, nonempty: bool = True) -> str:
    if type(value) is not str:
        raise EvaluationError(f"{name} must be a string")
    if nonempty and not value.strip():
        raise EvaluationError(f"{name} must not be empty")
    if len(value) > maximum:
        raise EvaluationError(f"{name} exceeds {maximum} characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EvaluationError(f"{name} must contain valid Unicode") from exc
    return value


def _findings(value: Any, context: str, line_count: int | None = None) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise EvaluationError(f"{context} must be a list")
    if len(value) > MAX_FINDINGS_PER_TASK:
        raise EvaluationError(f"{context} exceeds {MAX_FINDINGS_PER_TASK} findings")
    seen: set[tuple[str, int]] = set()
    result: list[dict[str, Any]] = []
    for finding in value:
        _fields(finding, {"rule_id", "line"}, f"{context} finding")
        rule = finding["rule_id"]
        if type(rule) is not str or rule not in RULE_IDS:
            raise EvaluationError(f"{context} has an unsupported rule_id")
        line = finding["line"]
        if type(line) is not int or not 1 <= line <= MAX_LINE_NUMBER:
            raise EvaluationError(f"{context} line must be a positive bounded integer, not bool")
        if line_count is not None and line > line_count:
            raise EvaluationError(f"{context} line {line} exceeds source line count {line_count}")
        pair = (rule, line)
        if pair in seen:
            raise EvaluationError(f"{context} has duplicate finding {pair!r}")
        seen.add(pair)
        result.append({"rule_id": rule, "line": line})
    return result


def _records(value: Any, name: str, *, allow_empty: bool) -> None:
    if type(value) is not list:
        raise EvaluationError(f"{name} must be a list")
    if not allow_empty and not value:
        raise EvaluationError(f"{name} must not be empty")
    if len(value) > MAX_RECORDS:
        raise EvaluationError(f"{name} exceeds {MAX_RECORDS} records")


def _source_line_count(source: str) -> int:
    """Count Python physical lines (CRLF, CR, LF), without a trailing phantom."""
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized:
        return 0
    return normalized.count("\n") + int(not normalized.endswith("\n"))


def _validate_dataset(dataset: Any) -> list[dict[str, Any]]:
    _records(dataset, "dataset", allow_empty=False)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_bytes = 0
    for record in dataset:
        _fields(record, {"id", "source", "path", "expected", "explanation"}, "dataset record")
        identifier = _text(record["id"], "dataset id", MAX_ID_CHARS)
        if identifier in seen:
            raise EvaluationError(f"duplicate dataset id: {identifier!r}")
        seen.add(identifier)
        source = _text(record["source"], f"{identifier} source", MAX_SOURCE_BYTES, nonempty=False)
        size = len(source.encode("utf-8"))
        if size > MAX_SOURCE_BYTES:
            raise EvaluationError(f"{identifier} source exceeds {MAX_SOURCE_BYTES} bytes")
        source_bytes += size
        if source_bytes > MAX_TOTAL_SOURCE_BYTES:
            raise EvaluationError(f"dataset sources exceed {MAX_TOTAL_SOURCE_BYTES} bytes")
        path = _text(record["path"], f"{identifier} path", MAX_PATH_CHARS)
        explanation = _text(
            record["explanation"], f"{identifier} explanation", MAX_EXPLANATION_CHARS
        )
        expected = _findings(
            record["expected"], f"{identifier} expected", _source_line_count(source)
        )
        result.append(
            {
                "id": identifier,
                "source": source,
                "path": path,
                "expected": expected,
                "explanation": explanation,
            }
        )
    _check_serialized_size(result, "dataset")
    return result


def _validate_predictions(predictions: Any) -> list[dict[str, Any]]:
    _records(predictions, "predictions", allow_empty=True)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in predictions:
        _fields(record, {"id", "findings"}, "prediction record")
        identifier = _text(record["id"], "prediction id", MAX_ID_CHARS)
        if identifier in seen:
            raise EvaluationError(f"duplicate prediction id: {identifier!r}")
        seen.add(identifier)
        findings = _findings(record["findings"], f"{identifier} findings")
        result.append({"id": identifier, "findings": findings})
    _check_serialized_size(result, "predictions")
    return result


def _check_serialized_size(records: list[dict[str, Any]], name: str) -> None:
    # Direct API callers receive the same aggregate bound as JSONL callers.
    size = sum(
        len(json.dumps(record, ensure_ascii=False).encode("utf-8")) + 1 for record in records
    )
    if size > MAX_INPUT_BYTES:
        raise EvaluationError(f"{name} exceeds {MAX_INPUT_BYTES} serialized bytes")


def load_dataset(path: Path) -> list[dict[str, Any]]:
    """Load a bounded UTF-8 JSONL dataset with exact schemas and authored labels."""
    return _validate_dataset(_load_jsonl(path))


def load_predictions(path: Path) -> list[dict[str, Any]]:
    """Load bounded JSONL predictions; source-relative bounds are checked later."""
    return _validate_predictions(_load_jsonl(path))


def _pairs(findings: list[dict[str, Any]]) -> set[tuple[str, int]]:
    return {(finding["rule_id"], finding["line"]) for finding in findings}


def _as_findings(pairs: set[tuple[str, int]]) -> list[dict[str, Any]]:
    return [
        {"rule_id": rule, "line": line}
        for rule, line in sorted(pairs, key=lambda pair: (pair[1], pair[0]))
    ]


def evaluate(dataset: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate and score exact findings without parsing or executing source.

    See the module documentation for task, missing-prediction, micro, and
    zero-denominator conventions. Unknown task IDs and out-of-source predicted
    lines are errors rather than ignored or clipped. Result task order follows
    dataset order; finding arrays are sorted by line then rule ID.
    """
    validated_dataset = _validate_dataset(dataset)
    validated_predictions = _validate_predictions(predictions)
    dataset_ids = {record["id"] for record in validated_dataset}
    prediction_by_id = {record["id"]: record["findings"] for record in validated_predictions}
    unknown = set(prediction_by_id) - dataset_ids
    if unknown:
        raise EvaluationError(f"unknown prediction ids: {', '.join(sorted(unknown))}")
    tasks: list[dict[str, Any]] = []
    total_tp = total_fp = total_fn = 0
    for record in validated_dataset:
        identifier = record["id"]
        supplied = identifier in prediction_by_id
        findings = prediction_by_id.get(identifier, [])
        _findings(findings, f"{identifier} findings", _source_line_count(record["source"]))
        expected = _pairs(record["expected"])
        predicted = _pairs(findings)
        tp, fp, fn = expected & predicted, predicted - expected, expected - predicted
        total_tp += len(tp)
        total_fp += len(fp)
        total_fn += len(fn)
        denominator = 2 * len(tp) + len(fp) + len(fn)
        task_score = (2 * len(tp) / denominator if denominator else 1.0) if supplied else 0.0
        tasks.append(
            {
                "id": identifier,
                "path": record["path"],
                "explanation": record["explanation"],
                "status": "evaluated" if supplied else "missing",
                "score": task_score,
                "true_positives": _as_findings(tp),
                "false_positives": _as_findings(fp),
                "false_negatives": _as_findings(fn),
            }
        )
    no_findings = total_tp + total_fp + total_fn == 0
    precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else float(no_findings)
    recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else float(no_findings)
    micro_denominator = 2 * total_tp + total_fp + total_fn
    micro_f1 = 2 * total_tp / micro_denominator if micro_denominator else 1.0
    return {
        "schema_version": SCHEMA_VERSION,
        "score": sum(task["score"] for task in tasks) / len(tasks),
        "metrics": {
            "micro_precision": precision,
            "micro_recall": recall,
            "micro_f1": micro_f1,
            "task_coverage": len(prediction_by_id) / len(validated_dataset),
        },
        "dataset_count": len(validated_dataset),
        "prediction_count": len(validated_predictions),
        "tasks": tasks,
    }
