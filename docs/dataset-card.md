# Synthetic dataset card

## Purpose

Exercise the input contract and scoring behavior of a small, offline code-review evaluation pipeline. The target labels are four explicitly defined AST risk patterns. This is not a general software-correctness or vulnerability benchmark.

## Origin and permissions

All samples are original synthetic Python snippets created for this repository. None were copied from an employer, client, private repository, paid annotation project, or external benchmark. The dataset is included under the repository's MIT license. Tooling and attribution are recorded in the [development note](development.md).

## Labeling approach

Each sample includes source, expected rule-and-line findings, and a rationale. The set contains clean controls, aliases, superficially similar but excluded constructs, and multiple-finding examples. Expected labels are committed independently of the scanner implementation.

`example_predictions.jsonl` is a deliberately imperfect, illustrative review submission. It is not attributed to a model or a person. Use it to inspect partial credit, false positives, and missed findings.

## Limitations

- The dataset is small, public, synthetic, and restricted to Python and four rules.
- Matching is exact by rule and line, so a logically correct finding on an adjacent line may not match.
- Public labels make it unsuitable for claims about unseen-task generalization.
- The deterministic baseline implements the same rule vocabulary; its score is not evidence of LLM capability.
- Syntax-tree heuristics do not determine exploitability or intent.
- There is no human-rater agreement study, external audit, or production validation.

For a serious model comparison, collect a separate permissioned dataset, define ambiguous cases before labeling, use independent reviewers, hold out test cases, and report uncertainty and error slices rather than only one aggregate score.
