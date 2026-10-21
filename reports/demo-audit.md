# Repository audit

Static heuristics and a small public synthetic benchmark are not a security certification or evidence of real-world model performance.

- Python files scanned: 2
- Files skipped: 0
- Findings: 4

| Rule | Severity | Path | Line | Evidence |
| --- | --- | --- | --- | --- |
| mutable-default | warning | sample.py | 6 | Mutable default may share state between calls; review intent. |
| dynamic-exec | warning | sample.py | 12 | Dynamic code execution needs trusted input and careful review. |
| shell-true | warning | sample.py | 16 | Subprocess uses shell=True; review command construction and trust boundaries. |
| bare-except | warning | sample.py | 22 | Bare except also catches process-control exceptions; review intent. |

## Repository metadata

- Present: readme — Found: a root README. Existence metadata only; contents and effectiveness are not assessed.
- Not found: license — Not found: a root license file. Existence metadata only; contents and effectiveness are not assessed.
- Not found: tests — Not found: a test directory or conventionally named Python test. Existence metadata only; contents and effectiveness are not assessed.
- Not found: ci — Not found: a recognized CI configuration. Existence metadata only; contents and effectiveness are not assessed.
