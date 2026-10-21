# Contributing

Small, well-tested improvements are welcome. Open an issue describing the expected behavior before adding a new rule or changing a scoring convention.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Optional lint, format, and coverage checks (development dependencies only):

```bash
python -m pip install . -r requirements-dev.txt
ruff check src tests
ruff format --check src tests
coverage run --source=repo_eval_workbench -m unittest discover -s tests
coverage report --fail-under=90
```

Add a positive example, a negative control, and failure-path tests for behavior changes. Keep runtime dependencies at zero. Do not execute submitted source or model outputs. Any new benchmark data must be original or explicitly licensed, with a rationale and provenance.

If report behavior changes intentionally, regenerate the example JSON, Markdown, and HTML artifacts and explain why the result changed. Do not weaken a threshold just to make CI green.
