"""Verify that tests and root modules work without local developer files."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PRIVATE_FILE_NAMES = {
    "llm.json",
    "aa_resources.json",
    "aa_assets.db",
    "aa_config.json",
    "llm_profiles.json",
    "cast.json",
}
PRIVATE_DIRECTORY_NAMES = {
    ".thumbs",
    "chapters",
    "out",
    "output",
    "release",
    "release-staging",
    "scripts",
    "staging",
}
SANITIZED_DATABASE_PATH = "data/halocue_labels.db"
APPROVED_CANDIDATE_FILES = (
    ".gitignore",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "tests/conftest.py",
    "tests/fixtures/aa_resources.min.json",
    "tests/fixtures/llm.empty.json",
    "tests/test_browser_fixture.py",
    "tests/test_verify_clean_source.py",
    "tools/verify_clean_source.py",
)


def _relative(path: Path, source: Path) -> str:
    return path.relative_to(source).as_posix()


def _private_path_label(
    value: str, *, enforce_database_allowlist: bool = False
) -> str | None:
    parts = tuple(
        part
        for part in value.replace("\\", "/").split("/")
        if part not in ("", ".")
    )
    if not parts:
        return None
    normalized = "/".join(parts)
    lowered_parts = tuple(part.lower() for part in parts)
    filename = lowered_parts[-1]
    if filename in PRIVATE_FILE_NAMES:
        return filename
    if filename.startswith("cast-") and filename.endswith(".json"):
        return "cast-*.json"
    private_directory = next(
        (part for part in lowered_parts if part in PRIVATE_DIRECTORY_NAMES), None
    )
    if private_directory is not None:
        return private_directory
    if enforce_database_allowlist and filename.endswith(".db"):
        if normalized == SANITIZED_DATABASE_PATH:
            return None
        return filename
    return None


def _is_root_expression(node: ast.AST, root_names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in root_names
    if isinstance(node, ast.Attribute):
        return _is_root_expression(node.value, root_names)
    if isinstance(node, ast.Subscript):
        return _is_root_expression(node.value, root_names)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_root_expression(node.left, root_names)
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    if (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id == "Path"
        and function.attr == "cwd"
    ):
        return True
    if isinstance(function, ast.Name) and function.id == "Path" and node.args:
        argument = node.args[0]
        if isinstance(argument, ast.Name) and argument.id == "__file__":
            return True
        return _is_root_expression(argument, root_names)
    if isinstance(function, ast.Attribute):
        return _is_root_expression(function.value, root_names)
    return False


def _root_names(tree: ast.AST) -> set[str]:
    names = {"HERE", "ROOT"}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not _is_root_expression(value, names):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in names:
                    names.add(target.id)
                    changed = True
    return names


def _constant_string_values(
    node: ast.AST, constants: dict[str, tuple[str, ...]]
) -> tuple[str, ...] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Tuple):
        values: list[str] = []
        for element in node.elts:
            resolved = _constant_string_values(element, constants)
            if resolved is None:
                return None
            values.extend(resolved)
        return tuple(values)
    return None


def _module_string_constants(tree: ast.AST) -> dict[str, tuple[str, ...]]:
    constants: dict[str, tuple[str, ...]] = {}
    if not isinstance(tree, ast.Module):
        return constants
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        value = statement.value
        if value is None:
            continue
        resolved = _constant_string_values(value, constants)
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if resolved is None:
                constants.pop(target.id, None)
            else:
                constants[target.id] = resolved
    return constants


def _literal_strings(
    node: ast.AST, constants: dict[str, tuple[str, ...]]
) -> list[str]:
    if isinstance(node, ast.Starred):
        return _literal_strings(node.value, constants)
    resolved = _constant_string_values(node, constants)
    if resolved is not None:
        return list(resolved)
    if isinstance(node, ast.JoinedStr):
        return [
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        ]
    return []


def _private_ast_references(tree: ast.AST) -> set[str]:
    labels: set[str] = set()
    roots = _root_names(tree)
    constants = _module_string_constants(tree)
    for node in ast.walk(tree):
        values: list[str] = []
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and _is_root_expression(node.left, roots)
        ):
            values.extend(_literal_strings(node.right, constants))
        elif isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name) and function.id in {"open", "Path"}:
                if node.args and (
                    function.id == "open" or not _is_root_expression(node, roots)
                ):
                    values.extend(_literal_strings(node.args[0], constants))
            elif (
                isinstance(function, ast.Attribute)
                and function.attr == "joinpath"
                and _is_root_expression(function.value, roots)
            ):
                for argument in node.args:
                    values.extend(_literal_strings(argument, constants))
            elif (
                isinstance(function, ast.Attribute)
                and function.attr == "join"
                and any(_is_root_expression(argument, roots) for argument in node.args)
            ):
                for argument in node.args:
                    values.extend(_literal_strings(argument, constants))
        for value in values:
            label = _private_path_label(value)
            if label is not None:
                labels.add(label)
    return labels


def _private_dependencies(source: Path) -> list[str]:
    failures: list[str] = []
    tests = source / "tests"
    if not tests.is_dir():
        return failures
    for path in sorted(tests.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            failures.append(
                f"test dependency scan failed: {_relative(path, source)}: {exc}"
            )
            continue
        for dependency in sorted(_private_ast_references(tree)):
            failures.append(
                f"private dependency: {_relative(path, source)} -> {dependency}"
            )
    return failures


def _git_files(source: Path) -> list[str] | None:
    root = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if root.returncode != 0 or Path(root.stdout.strip()).resolve() != source.resolve():
        return _public_manifest_files(source)
    result = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-z"],
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def _public_manifest_files(source: Path) -> list[str] | None:
    manifest = source / "PUBLIC_MANIFEST.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        entries = payload["files"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(entries, list):
        return None
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        relative = entry.get("path")
        size = entry.get("size")
        digest = entry.get("sha256")
        if not isinstance(relative, str) or not relative:
            return None
        normalized = relative.replace("\\", "/")
        parts = tuple(part for part in normalized.split("/") if part)
        if normalized.startswith("/") or ".." in parts or ":" in parts[0]:
            return None
        path = source.joinpath(*parts)
        if not path.is_file() or path.is_symlink():
            return None
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if size != len(data) or digest != hashlib.sha256(data).hexdigest():
            return None
        paths.append("/".join(parts))
    if paths != sorted(set(paths)):
        return None
    return paths


def _copy_file(source: Path, target: Path, relative: str) -> str | None:
    path = source / relative
    if not path.is_file() or path.is_symlink():
        return f"source manifest file unavailable: {relative}"
    destination = target / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return None


def _copy_clean_source(source: Path, target: Path) -> list[str]:
    failures: list[str] = []
    tracked = _git_files(source)
    if tracked is None:
        return ["tracked source manifest unavailable; refusing recursive copy"]
    manifest = set(tracked)
    for candidate in APPROVED_CANDIDATE_FILES:
        path = source / candidate
        if path.exists():
            if not path.is_file() or path.is_symlink():
                failures.append(f"approved candidate is not a regular file: {candidate}")
                continue
            manifest.add(candidate)
    for relative in sorted(manifest):
        if _private_path_label(relative, enforce_database_allowlist=True) is not None:
            failures.append(f"private source path: {relative}")
            continue
        failure = _copy_file(source, target, relative)
        if failure is not None:
            failures.append(failure)
    return failures


def _summary(output: str, limit: int = 8) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return " | ".join(lines[-limit:])


def _run_collection(source: Path, env: dict[str, str]) -> str | None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=source,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        return None
    return f"pytest collection failed ({result.returncode}): {_summary(result.stdout + result.stderr)}"


def _root_modules(source: Path) -> list[str]:
    return sorted(
        path.stem
        for path in source.glob("*.py")
        if path.name != "__init__.py"
    )


def _run_imports(source: Path, env: dict[str, str]) -> list[str]:
    failures: list[str] = []
    for module in _root_modules(source):
        code = (
            "import importlib,sys;"
            f"sys.path.insert(0,{str(source)!r});"
            f"importlib.import_module({module!r})"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", code],
            cwd=source,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            failures.append(
                f"module import failed: {module}: {_summary(result.stdout + result.stderr, 4)}"
            )
    return failures


def verify(source: Path) -> list[str]:
    source = source.resolve()
    if not source.is_dir():
        return [f"source directory not found: {source}"]
    failures = _private_dependencies(source)
    with tempfile.TemporaryDirectory(prefix="halocue-clean-source-") as copy_dir:
        clean_source = Path(copy_dir) / "source"
        clean_source.mkdir()
        failures.extend(_copy_clean_source(source, clean_source))
        with tempfile.TemporaryDirectory(prefix="halocue-user-data-") as user_data:
            env = os.environ.copy()
            env.update(
                {
                    "HALOCUE_USER_DATA_DIR": user_data,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONUTF8": "1",
                }
            )
            collection_failure = _run_collection(clean_source, env)
            if collection_failure:
                failures.append(collection_failure)
            failures.extend(_run_imports(clean_source, env))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args(argv)
    failures = verify(args.source)
    if failures:
        print("clean source verification failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("clean source verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
