"""Command-line interface; scanned programs and model outputs are never executed."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from . import __version__
from .audit import analyze_source, scan_repository
from .evaluation import evaluate, load_dataset, load_predictions
from .reporting import render_report


def unit_interval(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("must be a finite number between 0 and 1")
    return number


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="repo-eval", description="Static repository checks and offline code-review evaluation."
    )
    result.add_argument("--version", action="version", version=__version__)
    commands = result.add_subparsers(dest="command", required=True)
    audit = commands.add_parser(
        "audit", help="Read Python source without importing or executing it"
    )
    audit.add_argument("path", type=Path)
    audit.add_argument("--fail-on", choices=("none", "warning", "any"), default="none")
    scoring = commands.add_parser("evaluate", help="Score structured review predictions")
    scoring.add_argument("--dataset", type=Path, required=True)
    scoring.add_argument("--predictions", type=Path, required=True)
    scoring.add_argument("--fail-under", type=unit_interval, default=0.0)
    baseline = commands.add_parser("baseline", help="Generate deterministic AST-rule predictions")
    baseline.add_argument("--dataset", type=Path, required=True)
    baseline.add_argument("--output", type=Path)
    for command in (audit, scoring):
        command.add_argument("--format", choices=("json", "markdown", "html"), default="json")
        command.add_argument("--output", type=Path)
    return result


def _write(content: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
    else:
        # Do not silently overwrite an input or previous report.
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            if not content.endswith("\n"):
                handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "baseline":
            records = []
            dataset = load_dataset(args.dataset)
            for task in dataset:
                detected = analyze_source(task["source"], task["path"])
                if any(item["severity"] == "error" for item in detected):
                    raise ValueError(
                        f"{task['id']}: baseline could not analyze source; "
                        "no predictions were written"
                    )
                findings = sorted(
                    {
                        (item["rule_id"], item["line"])
                        for item in detected
                        if item["rule_id"]
                        in {"mutable-default", "bare-except", "shell-true", "dynamic-exec"}
                    }
                )
                records.append(
                    {
                        "id": task["id"],
                        "findings": [{"rule_id": rule, "line": line} for rule, line in findings],
                    }
                )
            # Enforce exactly the same prediction contract as externally supplied reviews.
            evaluate(dataset, records)
            _write("\n".join(json.dumps(record, sort_keys=True) for record in records), args.output)
            return 0
        if args.command == "audit":
            report = scan_repository(args.path)
            _write(render_report(report, args.format), args.output)
            findings = report["findings"]
            if any(item["severity"] == "error" for item in findings):
                return 2
            failed = args.fail_on == "any" and bool(findings)
            failed = failed or (
                args.fail_on == "warning"
                and any(item["severity"] == "warning" for item in findings)
            )
            return int(failed)
        report = evaluate(load_dataset(args.dataset), load_predictions(args.predictions))
        _write(render_report(report, args.format), args.output)
        return int(report["score"] < args.fail_under)
    except (OSError, ValueError, TypeError, RecursionError) as error:
        print(f"repo-eval: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
