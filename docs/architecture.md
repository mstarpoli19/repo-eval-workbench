# Architecture

Two inputs, one evidence-oriented reporting layer:

```text
Repository ── bounded file discovery ── Python AST heuristics ─┐
                                                            ├─ JSON / Markdown / HTML
JSONL dataset + review predictions ── validation ── scoring ──┘
```

`audit.py` owns read-only discovery and syntax-tree rules. `evaluation.py` validates dataset and prediction records and scores exact findings without relying on the scanner's answers. `reporting.py` renders plain result dictionaries. `cli.py` connects these components and owns exit codes and output files.

Ground truth lives in `data/benchmark.jsonl`, with a rationale for every synthetic example. Keeping labels outside the scanner makes it possible to catch a scanner regression rather than compute the expected answer using the same code being tested. These remain public development cases; they are not a hidden or independently collected test set.

## CLI behavior

- Exit **0**: command completed, with any requested score threshold met.
- Exit **1**: evaluation below `--fail-under`, or an audit finding meets `--fail-on`.
- Exit **2**: invalid input, filesystem failure, or invalid CLI usage.

Audit defaults to `--fail-on none`: finding a risk signal is not a proof that a repository is unsafe. Metadata checks never cause a policy failure by themselves. For CI integration, an owner can opt into `--fail-on warning` (the four risk rules) or `--fail-on any` (including informational skips). Read, decoding, parsing, and scan errors always return exit 2, even when the chosen risk policy would pass.

Output uses stdout unless `--output` is supplied. Output files must not already exist. The tool does not create parent directories or modify scanned files.

## Reproducibility

Source analysis and report ordering are deterministic. The example report is checked against a fresh run in CI. Successful reports use relative source paths and no time-dependent fields; filesystem failure diagnostics can include the input path. There are no calls to external models, no credentials, and no stochastic decoding.
