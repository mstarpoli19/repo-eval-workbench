# Scope and safety

## What an audit does not do

The audit does not import target modules, run tests from a target repository, install its packages, evaluate expressions, execute shell commands, resolve dependencies, call a model, or make network requests. It is a local source-inspection tool, not a sandboxed execution harness.

Only Python source is analyzed. A clean report does not establish correctness, absence of secrets, exploit resistance, or the quality of documentation/tests/CI. It cannot certify a repository for publication or deployment.

## File boundary

The scanner excludes common dependency/build directories and does not follow symbolic links. Individual Python files are limited to 1 MiB and the run is limited to 1,000 candidate Python files. Files skipped because of bounds or access errors are reported. The root must be a real directory, not a symlink.

Use a stable local checkout you control. The scanner is not designed to defend against a hostile process concurrently replacing files or a malicious filesystem. File descriptors and no-follow checks reduce accidental boundary mistakes; they are not a claim of complete adversarial isolation.

## Rule limitations

The AST rules intentionally trade coverage for inspectability. Import aliases and straightforward shadowing are handled, but Python's dynamic rebinding, metaprogramming, star imports, wrappers, and indirect calls can defeat static resolution. Passing `shell` as a variable is outside the literal-`True` rule. No whole-program dataflow or taint analysis is performed.

## Handling real data

Do not publish proprietary source or private model outputs in an evaluation report. This repository's examples are synthetic. Reports can include task IDs, paths, and findings. Treat reports derived from private code with the same care as the code itself.
