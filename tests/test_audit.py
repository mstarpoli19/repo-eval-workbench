"""Offline tests using newly authored synthetic examples only."""

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from repo_eval_workbench.audit import MAX_FILE_BYTES, analyze_source, scan_repository


def hits(source: str) -> list[tuple[str, int]]:
    return [(item["rule_id"], item["line"]) for item in analyze_source(source)]


class SourceTests(unittest.TestCase):
    def test_mutable_defaults_literals_calls_and_keyword_only(self):
        self.assertEqual(
            hits("def f(a=[], b={}, c={1}, d=list(), *, e=dict(), f=set()):\n pass\n"),
            [("mutable-default", 1)] * 6,
        )

    def test_nonmutable_and_arbitrary_calls_not_flagged(self):
        self.assertEqual(hits("def f(a=None, b=(), c=make_list(), d=str()):\n pass\n"), [])

    def test_async_and_lambda_defaults(self):
        self.assertEqual(
            hits("async def f(x=[]):\n pass\ng = lambda x={}: x\n"),
            [("mutable-default", 1), ("mutable-default", 3)],
        )

    def test_bare_except_only(self):
        self.assertEqual(hits("try:\n pass\nexcept:\n pass\n"), [("bare-except", 3)])
        self.assertEqual(hits("try:\n pass\nexcept Exception:\n pass\n"), [])

    def test_subprocess_module_alias_and_function_imports(self):
        for function in ("run", "call", "Popen", "check_output", "check_call"):
            with self.subTest(function=function):
                self.assertEqual(
                    hits(f"import subprocess as sp\nsp.{function}('x', shell=True)\n"),
                    [("shell-true", 2)],
                )
                self.assertEqual(
                    hits(f"from subprocess import {function} as invoke\ninvoke('x', shell=True)\n"),
                    [("shell-true", 2)],
                )

    def test_shell_false_variable_integer_and_unrelated_calls(self):
        self.assertEqual(
            hits(
                "import subprocess\nsubprocess.run('x', shell=False)\n"
                "subprocess.run('x', shell=enabled)\n"
                "subprocess.run('x', shell=1)\n"
                "other.run('x', shell=True)\n"
                "run('x', shell=True)\n"
            ),
            [],
        )

    def test_dynamic_execution(self):
        self.assertEqual(
            hits("eval('1')\nexec('x = 1')\n"), [("dynamic-exec", 1), ("dynamic-exec", 2)]
        )

    def test_shadowed_builtin_and_subprocess_names(self):
        source = """def f(eval, exec, list, subprocess):
 eval('1')
 exec('x')
 subprocess.run('x', shell=True)
 def g(x=list()):
  pass
def eval(value):
 return value
eval('1')
"""
        self.assertEqual(hits(source), [])
        self.assertEqual(
            hits("from subprocess import run\nrun = custom\nrun('x', shell=True)\n"), []
        )

    def test_nested_scopes_and_comprehension_binding(self):
        self.assertEqual(hits("def outer(eval):\n def inner():\n  eval('x')\n"), [])
        self.assertEqual(hits("[eval('x') for eval in functions]\n"), [])
        self.assertEqual(
            hits("class C:\n eval = custom\n def method(self):\n  eval('x')\n"),
            [("dynamic-exec", 4)],
        )

    def test_findings_have_contract_and_stable_order(self):
        source = "import subprocess\ndef f(x=[]):\n subprocess.run(eval('x'), shell=True)\n"
        first = analyze_source(source, "pkg/sample.py")
        self.assertEqual(first, analyze_source(source, "pkg/sample.py"))
        self.assertEqual(
            [(item["rule_id"], item["line"]) for item in first],
            [("mutable-default", 2), ("dynamic-exec", 3), ("shell-true", 3)],
        )
        self.assertEqual(set(first[0]), {"rule_id", "severity", "path", "line", "message"})
        self.assertTrue(all(item["path"] == "pkg/sample.py" for item in first))

    def test_parse_failure_is_not_clean(self):
        findings = analyze_source("def broken(:\n", "broken.py")
        self.assertEqual(findings[0]["rule_id"], "syntax-error")
        self.assertEqual(findings[0]["severity"], "error")
        self.assertEqual(findings[0]["line"], 1)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, name: str, content: str = "") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_scan_is_read_only_and_does_not_execute(self):
        marker = self.root / "should-not-exist"
        source = f"open({str(marker)!r}, 'w').write('executed')\neval('1')\n"
        target = self.write("module.py", source)
        before = target.read_bytes()
        report = scan_repository(self.root)
        self.assertFalse(marker.exists())
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(report["schema_version"], "1.0")
        self.assertEqual(report["files_scanned"], 1)
        self.assertEqual(report["files_skipped"], 0)
        self.assertEqual(report["findings"][0]["rule_id"], "dynamic-exec")

    def test_excluded_directories(self):
        for directory in (".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"):
            self.write(f"{directory}/hidden.py", "eval('1')")
        self.write("package/clean.py", "value = 1")
        report = scan_repository(self.root)
        self.assertEqual(report["files_scanned"], 1)
        self.assertEqual(report["findings"], [])

    def test_size_and_encoding_and_syntax_diagnostics(self):
        self.write("large.py", "#" * (MAX_FILE_BYTES + 1))
        self.write("boundary.py", "#" * MAX_FILE_BYTES)
        (self.root / "invalid.py").write_bytes(b"\xff\xfe")
        self.write("syntax.py", "if :")
        report = scan_repository(self.root)
        self.assertEqual(report["files_scanned"], 2)
        self.assertEqual(report["files_skipped"], 2)
        self.assertEqual(
            {item["rule_id"] for item in report["findings"]},
            {"file-too-large", "encoding-error", "syntax-error"},
        )

    def test_python_candidate_limit_is_explicit_and_deterministic(self):
        for index in range(5):
            self.write(f"{index}.py", "eval('1')")
        with patch("repo_eval_workbench.audit.MAX_PYTHON_FILES", 3):
            report = scan_repository(self.root)
            self.assertEqual(report, scan_repository(self.root))
        self.assertEqual(report["files_scanned"], 3)
        self.assertEqual(report["files_skipped"], 2)
        self.assertEqual(
            [item["path"] for item in report["findings"] if item["rule_id"] == "dynamic-exec"],
            ["0.py", "1.py", "2.py"],
        )
        self.assertIn("scan-limit", {item["rule_id"] for item in report["findings"]})

    def test_symlinks_are_not_read_or_followed(self):
        with tempfile.TemporaryDirectory() as outside:
            outside_root = Path(outside)
            (outside_root / "external.py").write_text("eval('1')", encoding="utf-8")
            (self.root / "linked.py").symlink_to(outside_root / "external.py")
            (self.root / "linked-directory").symlink_to(outside_root, target_is_directory=True)
            (self.root / "README.md").symlink_to(outside_root / "external.py")
            report = scan_repository(self.root)
        self.assertEqual(report["files_scanned"], 0)
        self.assertEqual(report["files_skipped"], 1)
        self.assertEqual({item["rule_id"] for item in report["findings"]}, {"symlink-skipped"})
        self.assertFalse(
            next(item["passed"] for item in report["checks"] if item["name"] == "readme")
        )

    def test_symlink_root_rejected(self):
        self.write("real/module.py", "eval('1')")
        link = self.root / "link"
        link.symlink_to(self.root / "real", target_is_directory=True)
        report = scan_repository(link)
        self.assertEqual(report["files_scanned"], 0)
        self.assertEqual(report["findings"][0]["rule_id"], "scan-error")

    def test_missing_root_is_explicit(self):
        report = scan_repository(self.root / "missing")
        self.assertEqual(report["files_scanned"], 0)
        self.assertEqual(report["findings"][0]["rule_id"], "scan-error")

    def test_permission_failure_is_explicit(self):
        self.write("denied.py", "eval('1')")
        original_open = os.open

        def selective_open(path, *args, **kwargs):
            if path == "denied.py":
                raise PermissionError("synthetic permission denial")
            return original_open(path, *args, **kwargs)

        with patch("repo_eval_workbench.audit.os.open", side_effect=selective_open):
            report = scan_repository(self.root)
        self.assertEqual(report["files_skipped"], 1)
        self.assertEqual(report["findings"][0]["rule_id"], "read-error")

    def test_metadata_checks_are_existence_only(self):
        report = scan_repository(self.root)
        self.assertEqual(
            {item["name"] for item in report["checks"]}, {"readme", "license", "tests", "ci"}
        )
        self.assertTrue(all(not item["passed"] for item in report["checks"]))
        self.write("README.md", "Synthetic project")
        self.write("LICENSE", "Synthetic placeholder")
        self.write("tests/test_example.py", "pass")
        self.write(".github/workflows/check.yml", "not: validated")
        report = scan_repository(self.root)
        self.assertTrue(all(item["passed"] for item in report["checks"]))
        self.assertTrue(
            all("Existence metadata only" in item["detail"] for item in report["checks"])
        )


if __name__ == "__main__":
    unittest.main()
