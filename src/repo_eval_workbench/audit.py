"""Read-only, deliberately limited Python risk heuristics.

Source is parsed as data, never imported or executed. Findings are review prompts,
not proof of a bug, exploit, or an otherwise secure repository.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import stat


MAX_FILE_BYTES = 1024 * 1024
MAX_PYTHON_FILES = 1000
EXCLUDED_DIRECTORIES = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}
)
_SUBPROCESS_CALLS = frozenset({"run", "call", "Popen", "check_output", "check_call"})


def _finding(rule_id: str, path: str, line: int, message: str, severity: str = "warning") -> dict:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "path": path,
        "line": line,
        "message": message,
    }


def _sort(findings: list[dict]) -> list[dict]:
    return sorted(
        findings, key=lambda item: (item["path"], item["line"], item["rule_id"], item["message"])
    )


class _Bindings(ast.NodeVisitor):
    """Collect conservative lexical bindings without entering child scopes."""

    def __init__(self) -> None:
        self.names: dict[str, tuple[str, str] | None] = {}
        self.external: set[str] = set()

    def bind(self, name: str, value: tuple[str, str] | None = None) -> None:
        if name in self.names and self.names[name] != value:
            self.names[name] = None
        else:
            self.names[name] = value

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bind(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.bind(name, ("module", "subprocess") if alias.name == "subprocess" else None)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.bind(
                alias.asname or alias.name,
                ("subprocess", alias.name)
                if node.level == 0
                and node.module == "subprocess"
                and alias.name in _SUBPROCESS_CALLS
                else None,
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.bind(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bind(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_ListComp(self, node: ast.ListComp) -> None:
        pass

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.bind(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name:
            self.bind(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self.bind(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.bind(node.rest)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.external.update(node.names)

    visit_Nonlocal = visit_Global


def _scope(nodes: list[ast.AST], arguments: ast.arguments | None = None) -> dict:
    bindings = _Bindings()
    for node in nodes:
        bindings.visit(node)
    if arguments is not None:
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            arguments.vararg,
            arguments.kwarg,
        ):
            if argument is not None:
                bindings.bind(argument.arg)
    return {name: value for name, value in bindings.names.items() if name not in bindings.external}


class _Analyzer(ast.NodeVisitor):
    def __init__(self, tree: ast.Module, path: str) -> None:
        self.path = path
        self.findings: list[dict] = []
        self.scopes: list[tuple[str, dict]] = [("module", _scope(tree.body))]

    def _resolve(self, name: str) -> tuple[str, str] | None:
        for _, bindings in reversed(self.scopes):
            if name in bindings:
                return bindings[name]
        return ("builtin", name)

    def _add(self, rule: str, node: ast.AST, message: str) -> None:
        self.findings.append(_finding(rule, self.path, node.lineno, message))

    def _defaults(self, arguments: ast.arguments) -> None:
        for default in (*arguments.defaults, *arguments.kw_defaults):
            if default is None:
                continue
            mutable = isinstance(default, (ast.List, ast.Dict, ast.Set))
            if isinstance(default, ast.Call) and isinstance(default.func, ast.Name):
                name = default.func.id
                mutable = name in {"list", "dict", "set"} and (
                    self._resolve(name) == ("builtin", name)
                )
            if mutable:
                self._add(
                    "mutable-default",
                    default,
                    "Mutable default may share state between calls; review intent.",
                )

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._defaults(node.args)
        for child in (
            *node.decorator_list,
            *node.args.defaults,
            *node.args.kw_defaults,
            node.returns,
        ):
            if child is not None:
                self.visit(child)
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
            node.args.vararg,
            node.args.kwarg,
        ):
            if argument is not None and argument.annotation is not None:
                self.visit(argument.annotation)
        previous = self.scopes
        self.scopes = [(kind, scope) for kind, scope in previous if kind != "class"]
        self.scopes.append(("function", _scope(node.body, node.args)))
        for child in node.body:
            self.visit(child)
        self.scopes = previous

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._defaults(node.args)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        previous = self.scopes
        self.scopes = [(kind, scope) for kind, scope in previous if kind != "class"]
        self.scopes.append(("function", _scope([node.body], node.args)))
        self.visit(node.body)
        self.scopes = previous

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for child in (*node.bases, *node.keywords, *node.decorator_list):
            self.visit(child)
        self.scopes.append(("class", _scope(node.body)))
        for child in node.body:
            self.visit(child)
        self.scopes.pop()

    def _comprehension(self, node: ast.AST) -> None:
        generators = node.generators
        self.visit(generators[0].iter)
        bindings = _scope([item.target for item in generators])
        previous = self.scopes
        self.scopes = [(kind, scope) for kind, scope in previous if kind != "class"]
        self.scopes.append(("comprehension", bindings))
        for index, generator in enumerate(generators):
            if index:
                self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self.scopes = previous

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self._add(
                "bare-except",
                node,
                "Bare except also catches process-control exceptions; review intent.",
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        subprocess_call = False
        if isinstance(function, ast.Name):
            resolved = self._resolve(function.id)
            subprocess_call = resolved is not None and resolved[0] == "subprocess"
            if function.id in {"eval", "exec"} and resolved == ("builtin", function.id):
                self._add(
                    "dynamic-exec",
                    node,
                    "Dynamic code execution needs trusted input and careful review.",
                )
        elif isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
            subprocess_call = function.attr in _SUBPROCESS_CALLS and (
                self._resolve(function.value.id) == ("module", "subprocess")
            )
        if subprocess_call and any(
            keyword.arg == "shell"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        ):
            self._add(
                "shell-true",
                node,
                "Subprocess uses shell=True; review command construction and trust boundaries.",
            )
        self.generic_visit(node)


def analyze_source(source: str, path: str = "sample.py") -> list[dict]:
    """Return sorted review heuristics, or an explicit parsing diagnostic."""
    try:
        tree = ast.parse(source, filename=path)
        analyzer = _Analyzer(tree, path)
        analyzer.visit(tree)
    except SyntaxError as error:
        return [
            _finding(
                "syntax-error",
                path,
                error.lineno or 1,
                "Source could not be parsed as Python: " + error.msg,
                "error",
            )
        ]
    except (ValueError, RecursionError) as error:
        return [
            _finding(
                "syntax-error", path, 1, "Source analysis failed: " + type(error).__name__, "error"
            )
        ]
    return _sort(analyzer.findings)


def _metadata(paths: set[str], directories: set[str]) -> list[dict]:
    root_names = {path.lower() for path in paths if "/" not in path}
    readme = any(
        name in root_names
        for name in ("readme", "readme.md", "readme.rst", "readme.txt", "readme.markdown")
    )
    license_present = any(
        name in root_names
        for name in (
            "license",
            "license.md",
            "license.txt",
            "licence",
            "licence.md",
            "licence.txt",
            "copying",
            "copying.txt",
        )
    )
    tests = bool({"tests", "test"} & directories) or any(
        Path(path).name.startswith("test_")
        and path.endswith(".py")
        or Path(path).name.endswith("_test.py")
        for path in paths
    )
    ci = any(
        path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml")) for path in paths
    ) or bool(
        paths
        & {
            ".gitlab-ci.yml",
            "Jenkinsfile",
            ".circleci/config.yml",
            "azure-pipelines.yml",
            "bitbucket-pipelines.yml",
        }
    )
    return [
        {
            "name": name,
            "passed": present,
            "detail": f"{'Found' if present else 'Not found'}: {description}. "
            "Existence metadata only; contents and effectiveness are not assessed.",
        }
        for name, present, description in (
            ("readme", readme, "a root README"),
            ("license", license_present, "a root license file"),
            ("tests", tests, "a test directory or conventionally named Python test"),
            ("ci", ci, "a recognized CI configuration"),
        )
    ]


def scan_repository(root: Path) -> dict:
    """Scan up to 1000 Python candidates without following filesystem symlinks.

    Successfully decoded files count as scanned, even when parsing fails. Skipped
    counts only encountered Python candidates that were not analyzed. Excluded
    directory contents are not enumerated. Directory-fd/no-follow support is
    required; unsupported platforms fail explicitly rather than weaken traversal.
    """
    report = {
        "schema_version": "1.0",
        "files_scanned": 0,
        "files_skipped": 0,
        "findings": [],
        "checks": [],
    }
    findings = report["findings"]
    paths: set[str] = set()
    directories: set[str] = set()
    root = Path(root).absolute()
    root_fd = None
    try:
        if root.is_symlink():
            raise OSError("Symlink repository roots are not scanned")
        if not hasattr(os, "fwalk") or not hasattr(os, "O_NOFOLLOW"):
            raise OSError("This platform lacks required no-follow directory-fd support")
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        candidates = 0
        limited = 0

        def traversal_error(error: OSError) -> None:
            findings.append(
                _finding(
                    "read-error",
                    ".",
                    1,
                    "A repository directory could not be enumerated: " + type(error).__name__,
                    "error",
                )
            )

        for current, dirs, files, directory_fd in os.fwalk(
            ".", topdown=True, onerror=traversal_error, follow_symlinks=False, dir_fd=root_fd
        ):
            prefix = Path(current)
            kept = []
            for name in sorted(dirs):
                if name in EXCLUDED_DIRECTORIES:
                    continue
                relative = (prefix / name).as_posix()
                try:
                    mode = os.stat(name, dir_fd=directory_fd, follow_symlinks=False).st_mode
                    if stat.S_ISLNK(mode):
                        findings.append(
                            _finding(
                                "symlink-skipped",
                                relative,
                                1,
                                "Symlink directory was not followed.",
                                "info",
                            )
                        )
                    elif stat.S_ISDIR(mode):
                        kept.append(name)
                        directories.add(relative)
                except OSError as error:
                    findings.append(
                        _finding(
                            "read-error",
                            relative,
                            1,
                            "Directory could not be inspected: " + type(error).__name__,
                            "error",
                        )
                    )
            dirs[:] = kept
            for name in sorted(files):
                relative = (prefix / name).as_posix()
                python_file = name.endswith(".py")
                try:
                    metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISLNK(metadata.st_mode):
                        if python_file:
                            report["files_skipped"] += 1
                        findings.append(
                            _finding(
                                "symlink-skipped", relative, 1, "Symlink file was not read.", "info"
                            )
                        )
                        continue
                    if not stat.S_ISREG(metadata.st_mode):
                        if python_file:
                            report["files_skipped"] += 1
                            findings.append(
                                _finding(
                                    "read-error",
                                    relative,
                                    1,
                                    "Non-regular Python candidate was not read.",
                                    "error",
                                )
                            )
                        continue
                    paths.add(relative)
                    if not python_file:
                        continue
                    if candidates >= MAX_PYTHON_FILES:
                        report["files_skipped"] += 1
                        limited += 1
                        continue
                    candidates += 1
                    descriptor = os.open(
                        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
                    )
                    with os.fdopen(descriptor, "rb") as source_file:
                        opened = os.fstat(source_file.fileno())
                        if not stat.S_ISREG(opened.st_mode):
                            raise OSError("Candidate changed to a non-regular file")
                        content = (
                            source_file.read(MAX_FILE_BYTES + 1)
                            if opened.st_size <= MAX_FILE_BYTES
                            else None
                        )
                    if content is None or len(content) > MAX_FILE_BYTES:
                        report["files_skipped"] += 1
                        findings.append(
                            _finding(
                                "file-too-large",
                                relative,
                                1,
                                "Python file exceeds the 1 MiB scan bound.",
                                "info",
                            )
                        )
                        continue
                    try:
                        source = content.decode("utf-8-sig")
                    except UnicodeDecodeError:
                        report["files_skipped"] += 1
                        findings.append(
                            _finding(
                                "encoding-error",
                                relative,
                                1,
                                "Python file is not valid UTF-8; not analyzed.",
                                "error",
                            )
                        )
                        continue
                    report["files_scanned"] += 1
                    findings.extend(analyze_source(source, relative))
                except OSError as error:
                    if python_file:
                        report["files_skipped"] += 1
                    findings.append(
                        _finding(
                            "read-error",
                            relative,
                            1,
                            "File could not be read safely: " + type(error).__name__,
                            "error",
                        )
                    )
        if limited:
            findings.append(
                _finding(
                    "scan-limit",
                    ".",
                    1,
                    f"Python candidate bound reached; {limited} additional files skipped.",
                    "info",
                )
            )
    except OSError as error:
        findings.append(
            _finding(
                "scan-error", ".", 1, "Repository scan could not complete: " + str(error), "error"
            )
        )
    finally:
        if root_fd is not None:
            os.close(root_fd)
    report["findings"] = _sort(findings)
    report["checks"] = _metadata(paths, directories)
    return report
